import serial                        
import time

PORT = 'COM4'
BAUDRATE = 1_000_000
READ = 0x02
WRITE = 0x03
ADDR_PRESENT_POSITION = 56
ADDR_GOAL_POSITION = 42
ser=serial.Serial(PORT, BAUDRATE, timeout = 0.2)
time.sleep(0.2)
print("커넥티드!!╰(*°▽°*)╯")
print("포트 = ",PORT)



def checksum(data):
    return (~sum(data)) & 0xFF

def make_packet(motor_id, instruction,params):
    length = len(params) +2
    body = [motor_id,length,instruction] + params
    return bytes([0xFF, 0xFF] + body + [checksum(body)])

def send_packet(ser,motor_id,instruction,params):
    packet = make_packet(motor_id,instruction,params)
    ser.reset_input_buffer()
    ser.write(packet)
    ser.flush()

def write_position(ser, motor_id, position):
    position = min(max(position, 0), 4095)
    low = position & 0xFF
    high = (position >> 8) & 0xFF
    send_packet(ser,motor_id,WRITE, [ADDR_GOAL_POSITION,low,high])

def write_byte(ser,motor_id,address,value):
    send_packet(ser,motor_id,WRITE,[address,value])

def read_position(ser, motor_id):
    send_packet(ser, motor_id, READ, [ADDR_PRESENT_POSITION,2])
    last_byte = b""
    while True:
        byte = ser.read()
        if not byte:
            raise TimeoutError("motor timeoutted")
        if last_byte==b"\xff" and byte == b"\xff":
            break
        last_byte = byte
    ser.read(1)
    length = ser.read(1)[0]
    ser.read(1)
    data= ser.read(length-1)

    low = data[0]
    high = data[1]
    return low + (high << 8)

motor_id = 1
start = 865
target = start+1000
print(start)
try:
    write_position(ser,motor_id,start)
    write_byte(ser,motor_id,40,1)
    while True:
        write_position(ser, motor_id, start+30)
        start = start+1
        time.sleep(0.001)
        print(read_position(ser,motor_id))
    write_position(ser, motor_id, target)
    time.sleep(0.5)
    write_position(ser,motor_id,start)
    time.sleep(0.5)
finally:
    write_byte(ser,motor_id,40,0)
    print("done!")
    ser.close()
    print("클로즈드!!(⊙_⊙)？")
# while True:
#     print(f" 1: {read_position(ser, motor_id=1)} 2: {read_position(ser, motor_id = 2)}, 3: {read_position(ser,motor_id = 3)}, 4: {read_position(ser, motor_id=4)} 5: {read_position(ser, motor_id = 5)}, 6: {read_position(ser,motor_id = 6)}")
