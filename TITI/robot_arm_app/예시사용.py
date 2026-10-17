"""실행 중인 REST 서버를 사용하는 간단한 그리퍼 제어 예제."""

from 클라이언트 import 로봇팔


def main() -> None:
    팔 = 로봇팔()
    print("현재 위치:", 팔.위치목록())
    팔.토크켜기()
    try:
        팔.잡기()
    finally:
        팔.토크끄기()
    print("motor_2 각도:", 팔.각도("motor_2"), "도")


if __name__ == "__main__":
    main()
