from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import re  # 정규 표현식을 위한 라이브러리

# .env 파일 로드
load_dotenv()

app = Flask(__name__)
# CORS(app, origins=["http://localhost:3000", "https://www.dongjinhub.store"])

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = 'https://www.dongjinhub.store'  # 클라이언트 도메인
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


# OpenAI API 키 설정
api_key = os.getenv("OPENAI_ASSISTANT_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID_LIM")

client = OpenAI(api_key=api_key)

@app.route('/chat', methods=['POST'])
def send_message():
    user_message = request.json.get('message')  # 프론트엔드에서 보내는 메시지 키는 'message'
    
    # 디버깅용 메시지 출력
    print("Received message:", user_message)
    app.logger.debug(f"Received message: {user_message}")

    if not user_message:
        return jsonify({"error": "메시지가 제공되지 않았습니다."}), 400

    try:
        # Thread 생성
        thread = client.beta.threads.create()

        # 어시스턴트에게 제공할 세부 지침 작성
        instructions = """임동진에 대해서 소개해줘 한국어로"""
        
        # Assistant에 대한 요청 수행
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID,
            instructions=instructions
        )

        # 완료를 기다리며 폴링
        while True:
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID
            )
            if run.status == "completed":
                break

        # 스레드 내의 메시지들 접근
        thread_messages = client.beta.threads.messages.list(thread.id)

        # 어시스턴트의 답변에서 텍스트 추출
        response_content = ""
        for content_block in thread_messages.data[-1].content:
            if hasattr(content_block.text, 'value'):  # Text 객체가 있는지 확인
                response_content += content_block.text.value  # Text 객체에서 값을 가져옴

        response_content = re.sub(r'【\d+:\d+†source】', '', response_content)
        response_content = re.sub(r'\[\d+:\d+\†source\]', '', response_content)

        return jsonify({"response": response_content.strip()}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Flask가 모든 인터페이스에서 접속할 수 있도록 설정하고, 포트 5000에서 실행
    app.run(host='0.0.0.0', port=5000, debug=True)
