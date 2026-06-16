docker exec -it someip_dissector /bin/bash

pip install scapy

someip_dissector/
├── pcap_parsers/
│   ├── pcap_reader.py          # 封装scapy/pyshark读取pcap
│   ├── tcp_reassembler.py      # TCP流重组
│   ├── someip_header.py        # SOME/IP头部结构定义与解析
│   └── transport_strategy.py   # UDP/TCP策略
├── arxml_parsers/
│   ├── arxml_parser.py         # 解析arxml，提取服务接口和数据类型
│   ├── type_factory.py         # 根据解析结果创建DataType对象
│   └── service_registry.py     # 服务查找表
├── datatypes/
│   ├── base.py                 # DataType抽象类
│   ├── primitives.py           # UInt8, UInt16, Int32...
│   ├── struct.py               # StructType
│   ├── array.py                # ArrayType与长度策略
│   ├── string.py               # 字符串类型
│   └── parse_context.py        # 解析上下文
├── deserialization/
│   ├── engine.py               # 核心反序列化引擎，协调所有组件
│   └── field_node.py           # 字段树节点
├── output/
│   ├── text_visitor.py         # 控制台树形输出
│   ├── json_visitor.py         # JSON输出
│   └── html_visitor.py         # HTML输出（可嵌入web）
├── web/
│   ├── app.py                  # Flask/FastAPI入口
│   ├── templates/
│   └── static/
├── utils/
│   └── logger.py
├── config.py                   # 全局配置
└── main.py                     # CLI入口，整合管道


解析链路：
    PCAP原始报文 → 解析传输层 (TCP/UDP) → 提取 SOME/IP 标准头部 → 提取五元组 + 报文类型 → 检索 ARXML 构建的全局注册表 → 定位到对应入参 / 出参 / 事件数据 / 字段 → 拿到数据类型定义 → 二进制 Payload 递归反序列化 → 结构化输出。