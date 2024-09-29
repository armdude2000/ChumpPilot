from cereal import car
from openpilot.selfdrive.car.chrysler.values import RAM_CARS, ChryslerFlagsSP

GearShifter = car.CarState.GearShifter
VisualAlert = car.CarControl.HUDControl.VisualAlert

def create_lkas_hud(packer, CP, lkas_active, mads_enabled, hud_alert, hud_count, car_model, auto_high_beam):
  commands = []

  # LKAS_HUD - Controls what lane-keeping icon is displayed

  # == Color ==
  # 0 hidden?
  # 1 white
  # 2 green
  # 3 ldw

  # == Lines ==
  # 03 white Lines
  # 04 grey lines
  # 09 left lane close
  # 0A right lane close
  # 0B left Lane very close
  # 0C right Lane very close
  # 0D left cross cross
  # 0E right lane cross

  # == Alerts ==
  # 7 Normal
  # 6 lane departure place hands on wheel

  color = 2 if lkas_active else 1 if mads_enabled and not lkas_active else 0
  lines = 3 if lkas_active else 0
  alerts = 7 if lkas_active else 0

  if hud_count < (1 * 4):  # first 3 seconds, 4Hz
    alerts = 1

  if hud_alert in (VisualAlert.ldw, VisualAlert.steerRequired):
    color = 4
    lines = 0
    alerts = 6

  values = {
    "LKAS_ICON_COLOR": color,
    "CAR_MODEL": car_model,
    "LKAS_LANE_LINES": lines,
    "LKAS_ALERTS": alerts,
  }

  if CP.carFingerprint in RAM_CARS:
    values['AUTO_HIGH_BEAM_ON'] = auto_high_beam
    values['LKAS_DISABLED'] = 0 if mads_enabled else 1

  commands.append(packer.make_can_msg("DAS_6", 0, values))

  if CP.spFlags & ChryslerFlagsSP.SP_RF_S20:
    commands.append(packer.make_can_msg("DAS_6", 1, values))

  return commands


def create_lkas_command(packer, CP, apply_steer, lkas_control_bit, frame):
  commands = []
  # LKAS_COMMAND Lane-keeping signal to turn the wheel
  enabled_val = 2 if CP.carFingerprint in RAM_CARS else 1
  values = {
    "STEERING_TORQUE": apply_steer,
    "LKAS_CONTROL_BIT": enabled_val if lkas_control_bit else 0,
    "COUNTER": frame % 0x10,
  }

  commands.append(packer.make_can_msg("LKAS_COMMAND", 0, values))

  if CP.spFlags & ChryslerFlagsSP.SP_RF_S20:
    commands.append(packer.make_can_msg("LKAS_COMMAND", 1, values))

  return commands


def create_cruise_buttons(packer, frame, bus, CP, cruise_buttons_msg=None, buttons=0, cancel=False, resume=False):

  acc_accel = 1 if buttons == 1 else 0
  acc_decel = 1 if buttons == 2 else 0

  values = {
    "ACC_Cancel": cancel,
    "ACC_Resume": resume,
    "ACC_Accel": acc_accel,
    "ACC_Decel": acc_decel,
    "COUNTER": frame % 0x10,
  }

  if buttons == 0 and not (cancel or resume) and CP.carFingerprint in RAM_CARS:
    values = cruise_buttons_msg.copy()
  return packer.make_can_msg("CRUISE_BUTTONS", bus, values)

def create_lkas_heartbit(packer, lkas_disabled, lkas_heartbit):
  # LKAS_HEARTBIT (697) LKAS heartbeat
  values = lkas_heartbit.copy()  # forward what we parsed
  values["LKAS_DISABLED"] = 1 if lkas_disabled else 0
  return packer.make_can_msg("LKAS_HEARTBIT", 0, values)

def create_ws_spoof(packer, ESP_6_msg, lkas_active): #344
  if lkas_active:
    values = {
      "WHEEL_SPEED_FL": 0,
      "WhlDir_FL_Stat": 0,
      "WHEEL_SPEED_FR": 0,
      "WhlDir_FR_Stat": 0,
      "WHEEL_SPEED_RL": 0,
      "WhlDir_RL_Stat": 0,
      "WHEEL_SPEED_RR": 0,
      "WhlDir_RR_Stat": 0, 
     } 
  else:
    values = ESP_6_msg.copy()  # Added parentheses here

  return packer.make_can_msg("ESP_6", 1, values)

def create_speed_1_spoof(packer, speed_1_msg, lkas_active): #514
  values = speed_1_msg.copy()

  if lkas_active:
    values = {
      "SPEED_LEFT": 0,
      "SPEED_RIGHT": 0,
    }

  return packer.make_can_msg("SPEED_1", 1, values)

def create_speed_spoof(packer, spoof_speed):  #284
  values = {
    "Vehicle_Speed": spoof_speed,
  }

  return packer.make_can_msg("ESP_8", 1, values)

def create_esp_5_spoof(packer): #292
    values = {
      "WhlPlsCnt_FL": 0,
      "WhlPlsCnt_FR": 0,
      "WhlPlsCnt_RL": 0,
      "WhlPlsCnt_RR": 0,
    }
    return packer.make_can_msg("ESP_5", 1, values)

def create_esp_4_spoof(packer): #332
  values = {
    "VehAccel_X": 0,
    "VehAccel_Y": 0,
  }
  return packer.make_can_msg("ESP_4", 1, values)

def create_ecm_1_spoof(packer): #264
  values = {
    "ENGINE_RPM": 900,
  }
  return packer.make_can_msg("ECM_1", 1, values)

def create_IC_1_spoof(packer): #784
  values = {
    "ODO": 56512.0,
  }
  return packer.make_can_msg("IC_1", 1, values)