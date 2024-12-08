from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import re
from pymongo import MongoClient
import certifi
from datetime import datetime, timezone

# .env 파일 로드
load_dotenv()

app = Flask(__name__)
CORS(app, origins=["https://www.dongjinhub.store"], supports_credentials=True)

# OpenAI API 키 설정
api_key = os.getenv("OPENAI_ASSISTANT_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID_LIM")

# client = OpenAI(api_key=api_key)

# MongoDB 연결 설정
mongo_uri = os.getenv("MONGODB")
mongo_client = MongoClient(mongo_uri, tlsCAFile=certifi.where())
db = mongo_client["chat_database"]
collection = db["chat_messages"]

@app.route('/chat', methods=['POST'])
def send_message():
    user_message = request.json.get('message')
    
    app.logger.debug(f"Received message: {user_message}")

    if not user_message:
        return jsonify({"error": "메시지가 제공되지 않았습니다."}), 400

    try:
        # Thread 생성
        thread = client.beta.threads.create()
        
        # Assistant에 대한 요청 수행
        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
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
            if hasattr(content_block.text, 'value'):
                response_content += content_block.text.value

        response_content = re.sub(r'【\d+:\d+†source】', '', response_content)
        response_content = re.sub(r'\[\d+:\d+\†source\]', '', response_content)

        # MongoDB에 질문과 응답 저장
        chat_data = {
            "user_message": user_message,
            "assistant_response": response_content.strip(),
            "timestamp": datetime.now(timezone.utc),
            "status": "success"  # 성공 상태
        }
        collection.insert_one(chat_data)

        return jsonify({"response": response_content.strip()}), 200

    except Exception as e:
        # 오류 정보 저장
        error_data = {
            "user_message": user_message,
            "error_message": str(e),
            "timestamp": datetime.now(timezone.utc),
            "status": "error"  # 오류 상태
        }
        collection.insert_one(error_data)

        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
