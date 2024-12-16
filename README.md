# url_analyzer
A url maliciousness detector that operates by crawling the url with playwright and then passing the crawled data to an LLM

# Local Deployment
You should have the following environment variables set
```
DOCKER_USERNAME
DOCKER_PASSWORD
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
ALLOW_CORS
URL_CLASSIFIER_REMOTE_BASE_PATH
OPENAI_API_KEY
JWT_SECRET_KEY
```

Install prerequisites with
```
pip install -r requirements.txt
```

You can classify a url by running
```
python url_analyzer/local/classify_url.py \
  --url http://github.com/
```
