from dataclasses import dataclass
import os
import time
from typing import Optional
from random import randint
from docker import DockerClient
from docker.models.containers import Container
from dataclasses import dataclass
import re
from typing import Optional
from docker import DockerClient
from docker.models.containers import Container

BIND_DIR_DOCKER = "/workdir"
RAW_TEXT_ENCODING = "ISO-8859-1"

ANSI_ESCAPE_8BIT = re.compile(
  br'(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])'
)
def _read_logline(raw_line: str) -> str:
  # 7-bit and 8-bit C1 ANSI sequences
  raw_line = ANSI_ESCAPE_8BIT.sub(b'', raw_line)
  return "".join([l if ord(l) < 128 else " " for l in raw_line.strip().decode(RAW_TEXT_ENCODING) ])

@dataclass
class DockerResult:
  error_status: int
  logs: str


class DockerClientContext:
  def __init__(self):
    self.docker_client = get_docker_client()
  
  def __enter__(self):
    return self.docker_client
  
  def __exit__(self, *args):
    self.docker_client.close()




class DockerContainerContext:

  def __init__(self, docker_client, **kwargs):
    self.container = docker_client.containers.run(**kwargs)
  
  def __enter__(self):
    return self.container
 
  def __exit__(self, *args):
    print(f"Killing container with id: {self.container.id}")
    try:
      self.container.kill()
      time.sleep(1)
    except Exception as e:
      print(f"Failed to kill container with id: {self.container.id} with error: {e}")
    else:
      print(f"Successfully killed container with id: {self.container.id}")





def get_docker_client() -> DockerClient:
  print("Loading DockerClient...")
  try:
    docker_client = DockerClient().from_env()
  except Exception as e:
    print('Docker is not running. Please start docker and try again.')
    raise ValueError()
  else:
    docker_client.login(username=os.environ['DOCKER_USERNAME'], password=os.environ['DOCKER_PASSWORD'])
  print("DockerClient Loaded!")
  return docker_client



def run_image_and_wait(
  docker_image: str,
  command: str,
  bind_dir_local: str,
  bind_dir_docker: str = BIND_DIR_DOCKER,
  docker_client: Optional[DockerClient] = None,
  detach: bool = False,
  stop_regex: Optional[str] = None,
  **kwargs
) -> DockerResult:
  docker_client = docker_client or DockerClient().from_env()

  try:
    print(f'Pulling Docker image {docker_image}')
    docker_client.images.pull(docker_image)
  except Exception as err:
    print('Failed to run docker - is it on your path?')
    raise err

  volumes =  {bind_dir_local: {"bind": bind_dir_docker, "mode": "rw"}}

  # Start the Docker container
  print(f"Running {command} in image {docker_image} using volumes {volumes} and {kwargs}")
  with DockerContainerContext(
    docker_client=docker_client,
    image=docker_image,
    command=command,
    volumes=volumes,
    detach=detach,
    **kwargs
  ) as container:
    
    print("Streaming Logs...")
    logs = ""
    for line in container.logs(stream=True):
      log_line = _read_logline(raw_line=line)
      print(log_line)
      logs += log_line + "\n"

      if stop_regex is not None and re.match(stop_regex, log_line):
        print(f"MATCHED STOP REGEX {stop_regex}")
        container.kill()
        break

    print("Waiting...")
    wait_result = container.wait()

  return DockerResult(
    error_status=wait_result['StatusCode'],
    logs=logs
  )
