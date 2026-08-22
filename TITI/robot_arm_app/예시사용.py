

from 클라이언트 import 로봇팔

팔 = 로봇팔()  # 기본: http://localhost:5000







print("현재 위치:", 팔.위치목록())

팔.토크켜기()
팔.잡기()
팔.토크끄기()

print("motor_2 각도:", 팔.각도("motor_2"), "도")
