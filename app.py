import os
import re
import time
import logging
import certifi
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from openai import OpenAI
from pymongo import MongoClient
from pymongo.server_api import ServerApi

# 1. 환경 변수 및 설정
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app, origins=[
    "https://dongjinhub.store",
    "https://www.dongjinhub.store",
    "http://localhost:3000",
], supports_credentials=True)

# OpenAI 설정
client = OpenAI(api_key=os.getenv("OPENAI_ASSISTANT_API_KEY"))
ASSISTANT_ID = os.getenv("ASSISTANT_ID_LIM")

# MongoDB 설정
MONGO_URI = os.getenv("MONGODB")
DB_NAME = os.getenv("DATABASE_NAME", "portfolio_chat")
COLL_NAME = os.getenv("COLLECTION_NAME", "chat_messages")

mongo = None
collection = None

# 2. 데이터베이스 관련 함수
def connect_mongo():
    """MongoDB 연결 초기화"""
    global mongo, collection
    if not MONGO_URI:
        logger.info("MongoDB URI 없음 - DB 비활성화")
        return

    try:
        mongo = MongoClient(
            MONGO_URI,
            server_api=ServerApi('1'),
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=5000
        )
        mongo.admin.command("ping") # 연결 테스트
        collection = mongo[DB_NAME][COLL_NAME]
        logger.info("✅ MongoDB 연결 성공")
    except Exception as e:
        logger.error(f"❌ MongoDB 연결 실패: {e}")
        mongo = None
        collection = None

def save_to_mongo(user_msg, ai_msg, thread_id, status="success", error_msg=None):
    """채팅 로그 저장 (성공/실패 통합)"""
    if collection is None: return

    doc = {
        "user_message": user_msg,
        "assistant_response": ai_msg,
        "error_message": error_msg,
        "thread_id": thread_id,
        "timestamp": datetime.now(timezone.utc),
        "status": status,
    }
    try:
        collection.insert_one(doc)
    except Exception as e:
        logger.warning(f"DB 저장 실패: {e}")

# 앱 시작 시 DB 연결
connect_mongo()

# 3. OpenAI 관련 헬퍼 함수
def clean_text(text):
    """OpenAI 응답에서 불필요한 소스 표기 제거"""
    if not text: return ""
    text = re.sub(r'【\d+:\d+†source】', '', text)
    text = re.sub(r'\[\d+:\d+†source\]', '', text)
    return text.strip()

def run_assistant(user_message, thread_id=None):
    """Assistant 실행 및 응답 대기"""
    # 1. 스레드 생성 또는 사용
    if not thread_id:
        thread = client.beta.threads.create()
        thread_id = thread.id

    # 2. 메시지 추가 및 실행
    client.beta.threads.messages.create(thread_id, role="user", content=user_message)
    run = client.beta.threads.runs.create(thread_id=thread_id, assistant_id=ASSISTANT_ID)

    # 3. 실행 완료 대기 (Polling)
    start_time = time.time()
    while time.time() - start_time < 60: # 60초 타임아웃
        run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
        
        if run_status.status == "completed":
            break
        if run_status.status in ["failed", "cancelled", "expired"]:
            error_detail = run_status.last_error if run_status.status == "failed" else "Unknown"
            raise Exception(f"Assistant Run Failed: {run_status.status} ({error_detail})")
        
        time.sleep(0.5)
    
    # 4. 응답 메시지 추출
    messages = client.beta.threads.messages.list(thread_id)
    last_msg = next((m for m in messages if m.run_id == run.id and m.role == "assistant"), None)
    
    if not last_msg:
        return "응답을 생성하지 못했습니다.", thread_id

    response_content = last_msg.content[0].text.value
    return clean_text(response_content), thread_id

def generate_suggestions(context_text):
    """GPT-3.5를 사용하여 추천 질문 생성 (JSON)"""
    try:
        sys_prompt = 'JSON 형식으로만 응답하세요: {"추천질문": ["질문1", "질문2", "질문3"]}'
        user_prompt = f"내용: {context_text[:500]}... \n이 내용과 관련하여 사용자가 할법한 질문 3가지를 추천해줘."
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-1106",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.warning(f"추천 질문 생성 실패: {e}")
        return "{}"

# 4. API 라우트
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "메시지가 없습니다."}), 400

    try:
        # 1. Assistant 실행
        response_text, thread_id = run_assistant(user_message)

        # 2. 추천 질문 생성 (병렬 처리가 아니므로 응답 속도 고려 필요)
        suggestions = generate_suggestions(response_text)

        # 3. DB 저장 (성공)
        save_to_mongo(user_message, response_text, thread_id, status="success")

        return jsonify({
            "response": response_text,
            "suggestions_content1": suggestions
        }), 200

    except Exception as e:
        logger.error(f"Chat Error: {e}")
        # DB 저장 (에러)
        save_to_mongo(user_message, None, None, status="error", error_msg=str(e))
        return jsonify({"error": str(e)}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "mongo": "connected" if collection is not None else "disconnected"
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)