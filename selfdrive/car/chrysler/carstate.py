from cereal import car
from common.conversions import Conversions as CV
from common.params import Params
from opendbc.can.parser import CANParser
from opendbc.can.can_define import CANDefine
from selfdrive.car.interfaces import CarStateBase
from selfdrive.car.chrysler.values import DBC, STEER_THRESHOLD, RAM_CARS, ChryslerFlags
from selfdrive.controls.lib.desire_helper import LANE_CHANGE_SPEED_MIN


class CarState(CarStateBase):
  def __init__(self, CP):
    super().__init__(CP)
    self.CP = CP
    can_define = CANDefine(DBC[CP.carFingerprint]["pt"])

    self.auto_high_beam = 0
    self.button_counter = 0
    self.lkas_car_model = -1
    self.lkasdisabled = 0
    self.lkasbuttonprev = 0

    if CP.carFingerprint in RAM_CARS:
      self.shifter_values = can_define.dv["Transmission_Status"]["Gear_State"]
    else:
      self.shifter_values = can_define.dv["GEAR"]["PRNDL"]

    self.param_s = Params()
    self.enable_mads = self.param_s.get_bool("EnableMads")
    self.mads_disengage_lateral_on_brake = self.param_s.get_bool("DisengageLateralOnBrake")
    self.acc_mads_combo = self.param_s.get_bool("AccMadsCombo")
    self.below_speed_pause = self.param_s.get_bool("BelowSpeedPause")
    self.e2eLongStatus = self.param_s.get_bool("ExperimentalMode")
    self.accEnabled = False
    self.madsEnabled = False
    self.leftBlinkerOn = False
    self.rightBlinkerOn = False
    self.disengageByBrake = False
    self.belowLaneChangeSpeed = True
    self.mads_enabled = None
    self.prev_mads_enabled = None
    self.prev_cruiseState_enabled = False
    self.prev_acc_mads_combo = None

  def update(self, cp, cp_cam, cp_eps):

    ret = car.CarState.new_message()

    self.prev_mads_enabled = self.mads_enabled
    self.e2eLongStatus = self.param_s.get_bool("ExperimentalMode")

    # lock info
    ret.doorOpen = any([cp.vl["BCM_1"]["DOOR_OPEN_FL"],
                        cp.vl["BCM_1"]["DOOR_OPEN_FR"],
                        cp.vl["BCM_1"]["DOOR_OPEN_RL"],
                        cp.vl["BCM_1"]["DOOR_OPEN_RR"]])
    ret.seatbeltUnlatched = cp.vl["ORC_1"]["SEATBELT_DRIVER_UNLATCHED"] == 1

    # brake pedal
    ret.brake = 0
    ret.brakePressed = cp.vl["ESP_1"]['Brake_Pedal_State'] == 1  # Physical brake pedal switch
    ret.brakeLights = bool(cp.vl["ESP_1"]["BRAKE_PRESSED_ACC"] or ret.brakePressed)

    # gas pedal
    ret.gas = cp.vl["ECM_5"]["Accelerator_Position"]
    ret.gasPressed = ret.gas > 1e-5

    # car speed
    if self.CP.carFingerprint in RAM_CARS:
      ret.vEgoRaw = cp.vl["ESP_8"]["Vehicle_Speed"] * CV.KPH_TO_MS
      ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(cp.vl["Transmission_Status"]["Gear_State"], None))
    else:
      ret.vEgoRaw = (cp.vl["SPEED_1"]["SPEED_LEFT"] + cp.vl["SPEED_1"]["SPEED_RIGHT"]) / 2.
      ret.gearShifter = self.parse_gear_shifter(self.shifter_values.get(cp.vl["GEAR"]["PRNDL"], None))
    ret.vEgo, ret.aEgo = self.update_speed_kf(ret.vEgoRaw)
    ret.standstill = not ret.vEgoRaw > 0.001
    ret.wheelSpeeds = self.get_wheel_speeds(
      cp.vl["ESP_6"]["WHEEL_SPEED_FL"],
      cp.vl["ESP_6"]["WHEEL_SPEED_FR"],
      cp.vl["ESP_6"]["WHEEL_SPEED_RL"],
      cp.vl["ESP_6"]["WHEEL_SPEED_RR"],
      unit=1,
    )

    if self.CP.carFingerprint in RAM_CARS:
      self.esp8_counter = cp.vl["ESP_8"]["COUNTER"]

    self.belowLaneChangeSpeed = ret.vEgo < LANE_CHANGE_SPEED_MIN and self.below_speed_pause

    # button presses
    ret.leftBlinker, ret.rightBlinker = self.update_blinker_from_stalk(200, cp.vl["STEERING_LEVERS"]["TURN_SIGNALS"] == 1,
                                                                       cp.vl["STEERING_LEVERS"]["TURN_SIGNALS"] == 2)
    ret.genericToggle = cp.vl["STEERING_LEVERS"]["HIGH_BEAM_PRESSED"] == 1

    self.leftBlinkerOn = bool(cp.vl["STEERING_LEVERS"]["TURN_SIGNALS"] == 1)
    self.rightBlinkerOn = bool(cp.vl["STEERING_LEVERS"]["TURN_SIGNALS"] == 2)

    cp_steering = cp_eps if self.CP.flags == ChryslerFlags.RAM_HD_S0 else cp

    # steering wheel
    ret.steeringAngleDeg = cp.vl["STEERING"]["STEERING_ANGLE"] + cp.vl["STEERING"]["STEERING_ANGLE_HP"]
    ret.steeringRateDeg = cp.vl["STEERING"]["STEERING_RATE"]
    ret.steeringTorque = cp_steering.vl["EPS_2"]["COLUMN_TORQUE"]
    ret.steeringTorqueEps = cp_steering.vl["EPS_2"]["EPS_TORQUE_MOTOR"]
    ret.steeringPressed = abs(ret.steeringTorque) > STEER_THRESHOLD

    # cruise state
    cp_cruise = cp_cam if self.CP.carFingerprint in RAM_CARS else cp

    ret.cruiseState.available = cp_cruise.vl["DAS_3"]["ACC_AVAILABLE"] == 1
    ret.cruiseState.enabled = cp_cruise.vl["DAS_3"]["ACC_ACTIVE"] == 1
    ret.cruiseState.speed = cp_cruise.vl["DAS_4"]["ACC_SET_SPEED_KPH"] * CV.KPH_TO_MS
    ret.cruiseState.nonAdaptive = cp_cruise.vl["DAS_4"]["ACC_STATE"] in (1, 2)  # 1 NormalCCOn and 2 NormalCCSet
    ret.cruiseState.standstill = cp_cruise.vl["DAS_3"]["ACC_STANDSTILL"] == 1
    ret.accFaulted = cp_cruise.vl["DAS_3"]["ACC_FAULTED"] != 0

    self.mads_enabled = ret.cruiseState.available

    if self.prev_mads_enabled is None:
      self.prev_mads_enabled = self.mads_enabled

    if ret.cruiseState.available:
      if self.enable_mads:
        if not self.prev_mads_enabled and self.mads_enabled:
          self.madsEnabled = True
        if self.acc_mads_combo:
          if not self.prev_acc_mads_combo and ret.cruiseState.enabled:
            self.madsEnabled = True
          self.prev_acc_mads_combo = ret.cruiseState.enabled
    else:
      self.madsEnabled = False

    ret.endToEndLong = self.e2eLongStatus

    if not self.CP.pcmCruise or (self.CP.pcmCruise and self.CP.minEnableSpeed > 0) or not self.enable_mads:
      if self.prev_cruiseState_enabled:  # CANCEL
        if not ret.cruiseState.enabled:
          if not self.enable_mads:
            self.madsEnabled = False
      if ret.brakePressed:
        if not self.enable_mads:
          self.madsEnabled = False

    if self.CP.pcmCruise and self.CP.minEnableSpeed > 0:
      if ret.gasPressed and not ret.cruiseState.enabled:
        self.accEnabled = False
      self.accEnabled = ret.cruiseState.enabled or self.accEnabled

    if not self.CP.pcmCruise:
      ret.cruiseState.enabled = self.accEnabled

    if not self.enable_mads:
      if ret.cruiseState.enabled and not self.prev_cruiseState_enabled:
        self.madsEnabled = True
      elif not ret.cruiseState.enabled:
        self.madsEnabled = False
    self.prev_cruiseState_enabled = ret.cruiseState.enabled

    if self.CP.carFingerprint in RAM_CARS:
      self.auto_high_beam = cp_cam.vl["DAS_6"]['AUTO_HIGH_BEAM_ON']  # Auto High Beam isn't Located in this message on chrysler or jeep currently located in 729 message
      self.lkasbutton = (cp.vl["Center_Stack_2"]["LKAS_Button"] == 1) or (cp.vl["Center_Stack_1"]["LKAS_Button"] == 1)
      if self.lkasbutton == 1 and self.lkasdisabled == 0 and self.lkasbuttonprev == 0:
        self.lkasdisabled = 1
      elif self.lkasbutton == 1 and self.lkasdisabled == 1 and self.lkasbuttonprev == 0:
        self.lkasdisabled = 0
      self.lkasbuttonprev = self.lkasbutton

    ret.steerFaultTemporary = False
    ret.steerFaultPermanent = False

    if self.madsEnabled:
      if (not self.belowLaneChangeSpeed and (self.leftBlinkerOn or self.rightBlinkerOn)) or\
        not (self.leftBlinkerOn or self.rightBlinkerOn):
        if self.CP.carFingerprint in RAM_CARS:
          ret.steerFaultTemporary = cp_steering.vl["EPS_3"]["DASM_FAULT"] == 1
        else:
          ret.steerFaultPermanent = cp.vl["EPS_2"]["LKAS_STATE"] == 4

    # blindspot sensors
    if self.CP.enableBsm:
      ret.leftBlindspot = cp.vl["BSM_1"]["LEFT_STATUS"] == 1
      ret.rightBlindspot = cp.vl["BSM_1"]["RIGHT_STATUS"] == 1

    self.lkas_car_model = cp_cam.vl["DAS_6"]["CAR_MODEL"]
    self.cruise_cancel = cp.vl["CRUISE_BUTTONS"]["ACC_Cancel"]
    self.button_counter = cp.vl["CRUISE_BUTTONS"]["COUNTER"]
    self.cruise_buttons = cp.vl["CRUISE_BUTTONS"]

    return ret

  @staticmethod
  def get_cruise_signals():
    signals = [
      ("ACC_AVAILABLE", "DAS_3"),
      ("ACC_ACTIVE", "DAS_3"),
      ("ACC_FAULTED", "DAS_3"),
      ("ACC_STANDSTILL", "DAS_3"),
      ("COUNTER", "DAS_3"),
      ("ACC_SET_SPEED_KPH", "DAS_4"),
      ("ACC_STATE", "DAS_4"),
    ]
    checks = [
      ("DAS_3", 50),
      ("DAS_4", 50),
    ]
    return signals, checks

  @staticmethod
  def get_can_parser(CP):
    signals = [
      # sig_name, sig_address
      ("DOOR_OPEN_FL", "BCM_1"),
      ("DOOR_OPEN_FR", "BCM_1"),
      ("DOOR_OPEN_RL", "BCM_1"),
      ("DOOR_OPEN_RR", "BCM_1"),
      ("Brake_Pedal_State", "ESP_1"),
      ("BRAKE_PRESSED_ACC", "ESP_1"),
      ("Accelerator_Position", "ECM_5"),
      ("WHEEL_SPEED_FL", "ESP_6"),
      ("WHEEL_SPEED_RR", "ESP_6"),
      ("WHEEL_SPEED_RL", "ESP_6"),
      ("WHEEL_SPEED_FR", "ESP_6"),
      ("STEERING_ANGLE", "STEERING"),
      ("STEERING_ANGLE_HP", "STEERING"),
      ("STEERING_RATE", "STEERING"),
      ("TURN_SIGNALS", "STEERING_LEVERS"),
      ("HIGH_BEAM_PRESSED", "STEERING_LEVERS"),
      ("SEATBELT_DRIVER_UNLATCHED", "ORC_1"),
      ("ACC_Cancel", "CRUISE_BUTTONS"),
      ("ACC_Distance_Dec", "CRUISE_BUTTONS"),
      ("ACC_Accel", "CRUISE_BUTTONS"),
      ("ACC_Decel", "CRUISE_BUTTONS"),
      ("ACC_Resume", "CRUISE_BUTTONS"),
      ("Cruise_OnOff", "CRUISE_BUTTONS"),
      ("ACC_OnOff", "CRUISE_BUTTONS"),
      ("ACC_Distance_Inc", "CRUISE_BUTTONS"),
      ("COUNTER", "CRUISE_BUTTONS"),
    ]

    checks = [
      # sig_address, frequency
      ("ESP_1", 50),
      ("ESP_6", 50),
      ("STEERING", 100),
      ("ECM_5", 50),
      ("CRUISE_BUTTONS", 50),
      ("STEERING_LEVERS", 10),
      ("ORC_1", 2),
      ("BCM_1", 1),
    ]

    if CP.enableBsm:
      signals += [
        ("RIGHT_STATUS", "BSM_1"),
        ("LEFT_STATUS", "BSM_1"),
      ]
      checks.append(("BSM_1", 2))

    if not (CP.flags == ChryslerFlags.RAM_HD_S0):
      signals += [
        ("COUNTER", "EPS_2",),
        ("COLUMN_TORQUE", "EPS_2"),
        ("EPS_TORQUE_MOTOR", "EPS_2"),
        ("LKAS_STATE", "EPS_2"),
      ]
      checks += [
        ("EPS_2", 100),
      ]

    if CP.carFingerprint in RAM_CARS:
      signals += [
        ("Vehicle_Speed", "ESP_8"),
        ("COUNTER", "ESP_8"),
        ("Gear_State", "Transmission_Status"),
        ("LKAS_Button", "Center_Stack_1"),
        ("LKAS_Button", "Center_Stack_2"),
      ]
      checks += [
        ("ESP_8", 50),
        ("Transmission_Status", 50),
        ("Center_Stack_1", 1),
        ("Center_Stack_2", 1),
      ]

      if not (CP.flags == ChryslerFlags.RAM_HD_S0):
        signals.append(("DASM_FAULT", "EPS_3"))
        checks.append(("EPS_3", 50))
    else:
      signals += [
        ("PRNDL", "GEAR"),
        ("SPEED_LEFT", "SPEED_1"),
        ("SPEED_RIGHT", "SPEED_1"),
      ]
      checks += [
        ("GEAR", 50),
        ("SPEED_1", 100),
      ]
      signals += CarState.get_cruise_signals()[0]
      checks += CarState.get_cruise_signals()[1]

    return CANParser(DBC[CP.carFingerprint]["pt"], signals, checks, 0)

  @staticmethod
  def get_cam_can_parser(CP):
    signals = [
      # sig_name, sig_address, default
      ("CAR_MODEL", "DAS_6"),
    ]
    checks = [
      ("DAS_6", 4),
    ]

    if CP.carFingerprint in RAM_CARS:
      signals += [
        ("AUTO_HIGH_BEAM_ON", "DAS_6"),
      ]
      signals += CarState.get_cruise_signals()[0]
      checks += CarState.get_cruise_signals()[1]

    return CANParser(DBC[CP.carFingerprint]["pt"], signals, checks, 2)

  @staticmethod
  def get_eps_can_parser(CP):
    signals = [
    ]
    checks = [
    ]
    if (CP.flags == ChryslerFlags.RAM_HD_S0):
      signals += [
      ("COUNTER", "EPS_2",),
      ("COLUMN_TORQUE", "EPS_2"),
      ("EPS_TORQUE_MOTOR", "EPS_2"),
      ("LKAS_STATE", "EPS_2"),
      ("DASM_FAULT", "EPS_3"),
      ]
      checks += [
        ("EPS_2", 100),
        ("EPS_3", 50),
      ]

    return CANParser(DBC[CP.carFingerprint]["pt"], signals, checks, 1)
