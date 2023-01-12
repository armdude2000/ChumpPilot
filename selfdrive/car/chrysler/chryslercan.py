from cereal import car
from selfdrive.car.chrysler.values import RAM_CARS

GearShifter = car.CarState.GearShifter
VisualAlert = car.CarControl.HUDControl.VisualAlert

def create_lkas_hud(packer, CP, lkas_active, hud_alert, hud_count, car_model, CS):
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

  color = 2 if lkas_active and not CS.lkasdisabled else 1
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
    values = {
      "AUTO_HIGH_BEAM_ON": CS.auto_high_beam,
      "LKAS_Disabled":CS.lkasdisabled,
    }

  return packer.make_can_msg("DAS_6", 0, values)


def create_lkas_command(packer, CP, apply_steer, lkas_control_bit):
  # LKAS_COMMAND Lane-keeping signal to turn the wheel
  enabled_val = 2 if CP.carFingerprint in RAM_CARS else 1
  values = {
    "STEERING_TORQUE": apply_steer,
    "LKAS_CONTROL_BIT": enabled_val if lkas_control_bit else 0,
  }
  return packer.make_can_msg("LKAS_COMMAND", 0, values)


def create_cruise_buttons(packer, frame, bus, cruise_buttons, cancel=False, resume=False, accel = False, decel = False):
  
  if (cancel == True) or (resume == True) or (accel == True) or (decel == True):
    values = {
      "ACC_Cancel": cancel,
      "ACC_Resume": resume,
      "ACC_Accel": accel,
      "ACC_Decel": decel,
      "COUNTER": frame % 0x10,
    }
  else:
    values = cruise_buttons.copy()
  return packer.make_can_msg("CRUISE_BUTTONS", bus, values)

def acc_command(packer, counter, enabled, accel_go, torque, max_gear, standstill, decel, das_3, commalong):
  values = das_3.copy()  # forward what we parsed
  if commalong:
    values['ACC_AVAILABLE'] = 1
    values['ACC_ACTIVE'] = enabled
    values['COUNTER'] = counter % 0x10

    # values['ACC_GO'] = accel_go
    values['ACC_STANDSTILL'] = standstill
    values['GR_MAX_REQ'] = max_gear

    values['ACC_DECEL_REQ'] = enabled and decel is not None
    if decel is not None:
      values['ACC_DECEL'] = decel

    values['ENGINE_TORQUE_REQUEST_MAX'] = enabled and torque is not None
    if torque is not None:
      values['ENGINE_TORQUE_REQUEST'] = torque

  return packer.make_can_msg("DAS_3", 0, values)

def acc_log(packer, aTarget, vTarget, calcvTarget, aActual, vActual):
  values = {
    'OP_A_TARGET': aTarget,
    'OP_V_TARGET': vTarget,
    'CALC_V_TARGET': calcvTarget,
    'OP_A_ACTUAL': aActual,
    'OP_V_ACTUAL': vActual,
  }
  return packer.make_can_msg("ACC_LOG", 0, values)