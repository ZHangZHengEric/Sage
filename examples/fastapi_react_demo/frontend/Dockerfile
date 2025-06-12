FROM node:18-alpine

WORKDIR /app

COPY ./examples/fastapi_react_demo/frontend/package*.json ./
RUN npm install

COPY ./examples/fastapi_react_demo/frontend/. .

EXPOSE 3000

CMD ["npm", "run", "dev"]