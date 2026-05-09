FROM docker.elastic.co/elasticsearch/elasticsearch:8.19.7

# 安装 analysis-ik 插件
RUN ./bin/elasticsearch-plugin install --batch https://get.infini.cloud/elasticsearch/analysis-ik/8.19.7
