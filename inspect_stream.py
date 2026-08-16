import zmq
import json

def listen_to_clean_stream():
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect("tcp://localhost:5556")
    socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Listen to all topics

    print("--- Listening to Live Ingestion Stream (Port 5556) ---")
    while True:
        topic, payload = socket.recv_multipart()
        trade_data = json.loads(payload.decode("utf-8"))
        print(f"[{topic.decode('utf-8')}] Price: ${trade_data['price']:.2f} | Vol: {trade_data['volume']} | Seq ID: {trade_data['sequence_id']}")

if __name__ == "__main__":
    listen_to_clean_stream()