import os
from flask import Flask, jsonify, request, send_from_directory, render_template, url_for  # Flask should be imported directly from flask package
from chat import generate  # Import the generate function from chat.py

app = Flask(__name__)

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/api/generate", methods=["POST"])
def generate_api():
    if request.method == "POST":
        try:
            req_body = request.get_json()

            # Extract input parameters from the incoming JSON request
            user_input = req_body.get("user_input")
            monthly_income = req_body.get("monthly_income")
            categories = req_body.get("categories")
            recent_transactions = req_body.get("recent_transactions")

            # Call the generate function from chat.py
            generated_text = generate(user_input, monthly_income, categories, recent_transactions)

            return jsonify({"text": generated_text})

        except Exception as e:
            return jsonify({"error": str(e)})

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web', path)

if __name__ == "__main__":
    app.run(debug=True)
