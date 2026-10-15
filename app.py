from flask import Flask

app = Flask(__name__)


@app.route("/")
def index():
    return "<h1>看護師勤務表作成</h1><p>開発環境の準備ができました。</p>"


if __name__ == "__main__":
    app.run(debug=True)