
import RPi.GPIO as GPIO
import time
from matrixKeypad_RPi_GPIO import keypad
from RPLCD.i2c import CharLCD
import requests
import asyncio
import websockets

port = 3000
url = f"http://172.16.105.175:{port}"

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
trig = 5
echo = 6
solenoid = 12
GPIO.setup(trig, GPIO.OUT)
GPIO.setup(echo, GPIO.IN)
GPIO.setup(solenoid, GPIO.HIGH)
lcd = CharLCD('PCF8574', 0x27)
lcd.clear()

keypad_enabled = True
kp = keypad()
global_password = [0, 0, 0, 0]
digit_active = True  # 초기값 설정

async def digit_return(): # 키패드 입력 받기
    while True:
        digit = kp.getKey()
        if digit is not None:
            return digit
        await asyncio.sleep(0.1)

def check_distance(): # 거리 측정
    GPIO.output(trig, True)
    time.sleep(0.00001)
    GPIO.output(trig, False)

    start_time = time.time()
    stop_time = time.time()

    while GPIO.input(echo) == 0:
        start_time = time.time()

    while GPIO.input(echo) == 1:
        stop_time = time.time()

    elapsed_time = stop_time - start_time
    distance = (elapsed_time * 34300) / 2

    return distance

def display_lcd(message): # lcd 출력
    lcd.clear()
    lcd.write_string(message)

async def send_doorlock_status(status, timestamp): # db 서버에 로그 전송
    endpoint = "/doorlock-status"
    try:
        response = requests.post(url + endpoint, json={"status": status, "timestamp": timestamp})
        response.raise_for_status()
        print("서버 응답:", response.json())
    except requests.exceptions.RequestException as err:
        print(f"에러: {err}")

async def open_doorlock(): # 도어락 열기
    display_lcd("Open")
    GPIO.setup(solenoid, GPIO.LOW)
    door_state = "open"
    await send_doorlock_status(door_state, time.time())
    await asyncio.sleep(3)

    global distance_check_active  # global 선언 추가
    distance_check_active = True

    while distance_check_active and door_state == "open":
        distance = check_distance()
        print("distance: ", distance)
        await asyncio.sleep(1)

        if distance < 5: # 5cm 미만 감지되면 close
            await close_doorlock()
            distance_check_active = False

async def close_doorlock(): # 도어락 잠금
    display_lcd("Close")
    GPIO.setup(solenoid, GPIO.HIGH)
    door_state = "close"
    await send_doorlock_status(door_state, time.time())
    await asyncio.sleep(1)
    display_lcd("Enter Password")

async def error_doorlock(): # 비밀번호 오류 동작
    display_lcd("Error")
    door_state = "error"
    await send_doorlock_status(door_state, time.time())
    await asyncio.sleep(1)
    display_lcd("Enter Password")

async def mujeok(message): # 무적
    global keypad_enabled
    door_state = "mujeok"
    await send_doorlock_status(door_state, time.time())
    if message == "mujeok":
        keypad_enabled = False
    else:
        keypad_enabled = True

async def handle_doorlock(message): # 웹소켓 메세지 받아서 도어락 동작
    try:
        if message == "open":
            await open_doorlock()
        elif message == "close":
            await close_doorlock()
        elif message == "mujeok" or message == "unMujeok":
            display_lcd(message.capitalize())
            await mujeok(message)
            door_state = message
            await send_doorlock_status(door_state, time.time())

    except Exception as e:
        print(f"웹 소켓 연결 에러: {e}")

async def handle_pwChange(password_list): # 비밀번호 변경
    try:
        global global_password
        global_password = password_list
        door_state = "password change"
        await send_doorlock_status(door_state, time.time())
    except Exception as e:
        print(f"웹 소켓 연결 에러: {e}")

async def keypad_input_loop(): # 키패드 입력 받기
    global digit_active
    digit_active = True
    entered_password = []
    digit_count = 0

    while True:
        digit = await digit_return()
        if keypad_enabled and digit_active and digit is not None:
            entered_password.append(digit)
            digit_count += 1
            display_lcd("*" * digit_count)
            await asyncio.sleep(0.3)

            if digit_count == 4:
                if entered_password == global_password:
                    await open_doorlock()
                else:
                    await error_doorlock()

                entered_password = []
                digit_count = 0

async def main():
    try:
        global digit_active, distance_check_active
        door_state = "close" # 도어락 닫힘 상태 시작
        await close_doorlock()
        display_lcd("Enter Password")
        websocket = await websockets.connect("wss://port-0-door-lock-server-jvpb2alnwnfxkw.sel5.cloudtype.app/")
        print("웹 소켓 연결 성공")
        distance_check_active = False
        while True:
            message = await websocket.recv()
            if message.startswith("pwChange"): # 비밀번호 변경
                display_lcd("pwChange")
                password = message.split("-")[1] # 문자열에서 비밀번호 분리
                password_list = [int(digit) for digit in password] # int로 변환
                await handle_pwChange(password_list)
                global_password = password
            else:
                await handle_doorlock(message)

    except KeyboardInterrupt:
        print("main 함수 종료")

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(keypad_input_loop())
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("종료")
        GPIO.cleanup()
        lcd.clear()

