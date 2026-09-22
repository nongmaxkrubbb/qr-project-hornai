import os
from urllib.parse import urlsplit

from dotenv import load_dotenv
from werkzeug.serving import WSGIRequestHandler
load_dotenv()

from app import create_app

app = create_app()


class PrivateRequestHandler(WSGIRequestHandler):
    def log_request(self, code='-', size='-'):
        # Match production access logs: capability tokens stay out of terminal logs.
        self.log('info', '%s %s %s', self.command, urlsplit(self.path).path, code)


if __name__ == "__main__":
    # Dev only. Production: gunicorn -c gunicorn.conf.py run:app
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host="0.0.0.0", port=port, threaded=True, request_handler=PrivateRequestHandler)
