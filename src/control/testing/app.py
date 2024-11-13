from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Constants
MIN_VALUE = 5
MAX_VALUE = 100
STEP = 5  # This is the increment/decrement step

# Initialize the variable
variable_value = 50  # Start with a middle value for demonstration

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_value', methods=['GET'])
def get_value():
    return jsonify({"value": variable_value})

@app.route('/increment', methods=['POST'])
def increment():
    global variable_value
    variable_value = min(variable_value + STEP, MAX_VALUE)
    return jsonify({"value": variable_value})

@app.route('/decrement', methods=['POST'])
def decrement():
    global variable_value
    variable_value = max(variable_value - STEP, MIN_VALUE)
    return jsonify({"value": variable_value})

@app.route('/set_to_20', methods=['POST'])
def set_to_20():
    global variable_value
    variable_value = 20
    return jsonify({"value": variable_value})

if __name__ == '__main__':
    app.run(debug=True)
