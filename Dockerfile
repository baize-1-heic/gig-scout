FROM python:3.12-slim

# 纯标准库脚本，无第三方依赖
WORKDIR /app

COPY demand-scout.py /app/demand-scout.py

# 台账/状态写到容器内 /out，跑的时候挂卷出来
ENV DEMAND_SCOUT_DIR=/out
RUN mkdir -p /out

# 默认跑一轮侦察；CI 里会覆盖成 --self-test
CMD ["python", "demand-scout.py"]
