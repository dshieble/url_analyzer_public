import os
from typing import Optional
from fastapi import FastAPI, status, Request, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
import jwt

from url_analyzer.classification.api.api_key_generation import get_api_key_from_ip_address
from url_analyzer.classification.classifier.classifier import BasicUrlClassifier, validate_classification_inputs
from url_analyzer.classification.classifier.url_classification import RichUrlClassificationResponse
from url_analyzer.classification.api.rate_limit import RateLimiter



class HealthCheck(BaseModel):
  """Response model to validate and return when performing a health check."""

  status: str = "OK"

class ApiKey(BaseModel):
  """Response model to validate and return when performing a health check."""

  api_key: str

app = FastAPI()

# Allow CORS for the specified domain
allow_origins = (
  ["*"]
  if os.environ.get("ALLOW_CORS") == "True"
  else
  [
    "https://zerophishing-react-live.vercel.app",
    'https://www.zero-phishing.com'
  ]
)
print(f"[CORSMiddleware] allow_origins: {allow_origins}")
app.add_middleware(
  CORSMiddleware,
  allow_origins=allow_origins,
  allow_credentials=True,
  allow_methods=["*"],
  allow_headers=["*"],
)

JWT_SECRET_KEY = str(os.environ.get("JWT_SECRET_KEY"))

# JWT bearer scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

RATE_LIMITER = RateLimiter()

@app.get(
  "/",
  tags=["healthcheck"],
  summary="Perform a Health Check",
  response_description="Return HTTP Status Code 200 (OK)",
  status_code=status.HTTP_200_OK,
  response_model=HealthCheck,
)
def get_health() -> HealthCheck:
  """
  ## Perform a Health Check
  Endpoint to perform a healthcheck on. This endpoint can primarily be used Docker
  to ensure a robust container orchestration and management is in place. Other
  services which rely on proper functioning of the API service will not deploy if this
  endpoint returns any other HTTP status code except 200 (OK).
  Returns:
      HealthCheck: Returns a JSON response with the health status
  """
  return HealthCheck(status="OK")

@app.post("/classify")
async def classify_url(url: str, token: str = Depends(oauth2_scheme)) -> RichUrlClassificationResponse:
  print(f"[classify_url] url: {url}, token: {token}")

  # Validate token
  try:
   jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
  except jwt.ExpiredSignatureError:
    raise HTTPException(status_code=403, detail="Token has expired")
  except jwt.exceptions.DecodeError:
    raise HTTPException(status_code=403, detail="Invalid token")
  else:
    # Rate limit check
    if RATE_LIMITER.is_rate_limited(token=token):
      raise HTTPException(status_code=429, detail=f"Rate limit exceeded. Try again after {RATE_LIMITER.window_size_in_minutes} minutes.")
    else:
      # Validate classification inputs
      error = validate_classification_inputs(url=url)
      if error is not None:
        raise HTTPException(status_code=500, detail=error)

      # Classify URL
      maybe_rich_classification_response = await BasicUrlClassifier().classify_url(url=url)
      if maybe_rich_classification_response.error is not None:
        raise HTTPException(status_code=500, detail=maybe_rich_classification_response.error)

      return maybe_rich_classification_response.content


@app.get("/get_api_key")
async def get_ip(request: Request):
  print(f"[get_ip] request.client.host: {request.client.host}")
  ip_address = request.client.host
  api_key = get_api_key_from_ip_address(ip_address=ip_address)
  return ApiKey(api_key=api_key)
  
if __name__ == "__main__":
  """
  fastapi run url_analyzer/api/start_api.py  --host 0.0.0.0 --port 8000
  """
  pass
