FROM rust:latest
LABEL author daiqian <alexdai@vivo.com>

ENV RUSTUP_DIST_SERVER https://mirrors.tuna.tsinghua.edu.cn/rustup
ENV RUSTUP_UPDATE_ROOT https://mirrors.tuna.tsinghua.edu.cn/rustup/rustup
RUN rustup default stable && \
    rustup target add armv7a-none-eabi && \
    cargo install cargo-binutils && \
    rustup component add llvm-tools-preview && \
    rustup component add rust-src && \
    rustup component add rustfmt
ADD sources.list /etc/apt/
ADD config ~/.cargo/
COPY . /app/

# 信任来自 https://apt.llvm.org/ 的 PGP 公钥
RUN wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add -

RUN DEBIAN_FRONTEND=noninteractive apt-get update -y && \
    apt-get install git   wget bzip2 \
    build-essential  libncurses-dev  cppcheck   \
    gcc-arm-none-eabi gdb-arm-none-eabi binutils-arm-none-eabi  qemu-system-arm    \
    python3-pip  python3-requests  -y   \
    scons \
    libclang-dev && \
    apt-get clean -y

# Install Dependencies： clang-14, llvm-14, graphviz
RUN DEBIAN_FRONTEND=noninteractive apt-get install clang-14 llvm-14 graphviz -y
RUN ln -sf /usr/bin/clang-14 /usr/bin/clang

# Install Python
RUN wget https://mirrors.huaweicloud.com/python/3.11.10/Python-3.11.10.tgz && \
    tar -zxvf Python-3.11.10.tgz && \
    cd Python-3.11.10 && \
    ./configure --enable-optimizations && \
    make -j 8 && \
    make install && \
    cd .. && \
    rm -rf Python-3.11.10 Python-3.11.10.tgz && \
    ln -sf /usr/bin/python3 /usr/bin/python

RUN apt install python3-venv -y
RUN pip config set global.index-url https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# python 依赖
RUN python3 -m venv /app/transfactor_venv && \
    /app/transfactor_venv/bin/pip install --no-cache-dir -r /app/requirements.txt
RUN echo "source /app/transfactor_venv/bin/activate" >> ~/.bashrc

CMD ["bash", "-l"]
