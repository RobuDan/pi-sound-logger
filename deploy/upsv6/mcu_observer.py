# Run on the UPS PikaPython interpreter, NOT with Raspberry Pi Python.
# Telemetry only. No output control, timers, register writes, or poweroff.
from UPS import Device

print("UPS_OBSERVER_V1")
print(Device.getInfo())
print("OBS columns: runtime_ms,input_mv,battery_mv,output_mv,input_state,output_state,battery_zone")

last_input = -1
last_output = -1
last_zone = -1
last_valid = -1
records = 0
ticks = 0

while True:
    iv = Device.getInputVoltage()
    bv = Device.getBatteryVoltage()
    ov = Device.getOutputVoltage()
    valid = 4000 <= bv and bv <= 9000 and 0 <= iv and iv <= 22000 and 0 <= ov and ov <= 6000
    if valid:
        input_state = last_input
        if iv >= 4000:
            input_state = 1
        elif iv <= 1000 or input_state < 0:
            input_state = 0
        output_state = 1
        if ov < 1000:
            output_state = 0
        elif ov >= 4500:
            output_state = 2
        zone = last_zone
        if bv > 8000:
            zone = 2
        elif bv <= 7600:
            zone = 0
        elif zone < 0 or zone == 0 and bv >= 7650 or zone == 2 and bv <= 7950:
            zone = 1
        changed = input_state != last_input or output_state != last_output or zone != last_zone or last_valid != 1
        if changed and records < 24:
            print("OBS," + str(Device.getRuntime()) + "," + str(iv) + "," + str(bv) + "," + str(ov) + "," + str(input_state) + "," + str(output_state) + "," + str(zone))
            records = records + 1
        last_input = input_state
        last_output = output_state
        last_zone = zone
    elif last_valid != 0 and records < 24:
        print("OBS_INVALID," + str(Device.getRuntime()) + "," + str(iv) + "," + str(bv) + "," + str(ov))
        records = records + 1
    last_valid = valid
    if records == 24:
        print("OBS_LIMIT: later transitions will not be printed")
        records = 25
    if ticks == 5:
        print("OBS_LIVE")
    ticks = ticks + 1
    Device.sleep(1000)
