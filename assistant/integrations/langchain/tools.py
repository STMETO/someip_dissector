"""LangChain Tool 适配入口。

第二阶段将在此把现有十四个领域 Tool 包装为 StructuredTool。当前模块先固定依赖
方向：只能调用 ``assistant.tools``，不能在适配层重复实现 SOME/IP 查询。
"""
