#!/bin/bash

IMAGE_NAME="base_core"
CONTAINER_NAME="base_core_container"

echo "🚀 Starting deployment for $IMAGE_NAME..."

# 1. Force remove the container first (Stops it if running, then deletes it)
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "Found existing container. Removing $CONTAINER_NAME..."
    docker rm -f $CONTAINER_NAME
fi

# 2. Force remove the image
# Adding -f here bypasses the "conflict" error you just saw
if [ "$(docker images -q $IMAGE_NAME)" ]; then
    echo "Removing existing image: $IMAGE_NAME"
    docker rmi -f $IMAGE_NAME
fi

# 3. Build the new image (CACHE_BUST ensures source files are always re-copied)
echo "Building new image..."
docker build --build-arg CACHE_BUST=$(date +%s) -t $IMAGE_NAME .

# 4. Run the new container
echo "Running new container: $CONTAINER_NAME"
docker run -p 8000:8000 --name $CONTAINER_NAME --env-file .env $IMAGE_NAME