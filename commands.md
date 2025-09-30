```bash
# 构建 Docker 镜像，镜像名为 transfactor2
docker build -t transfactor2 .
# 后台运行镜像 transfactor2，并指定容器名 transfactor2
docker run -it -d --rm --name transfactor2 -w /app transfactor2 /bin/bash
# 进入容器 transfactor2
docker exec -it transfactor2 /bin/bash
# 执行转译任务，并记录时间
nohup bash -c "time -p bash run.sh" > log.txt 2>&1 &
# 合并模块, 指定需要合并的文件夹
python Tool/transfactor/merge_modules.py -p Output/rust_project
# 执行测试
cd Output/rust_project
cargo build && cargo test --tests --no-fail-fast
```