"""Database table and column comments shared by ORM metadata and migrations."""

from sqlalchemy import MetaData


TABLE_COMMENTS: dict[str, dict[str, object]] = {
    "tasks": {
        "table": "后台任务主表",
        "columns": {
            "id": "任务主键", "type": "任务类型", "status": "任务状态",
            "source_batch_dir": "本次来源批次目录", "source_library_dir": "历史来源图库目录",
            "pod_pending_dir": "POD待处理目录", "pod_library_dir": "历史POD图库目录",
            "ratio_code": "输出或裁切比例编码", "archive_date": "归档日期",
            "settings_snapshot": "创建时冻结的配置快照", "counters": "任务计数器",
            "warnings": "任务警告列表", "idempotency_key": "幂等请求键",
            "lease_owner": "Worker租约持有者", "lease_until": "Worker租约到期时间",
            "started_at": "任务开始时间", "finished_at": "任务结束时间",
            "created_at": "记录创建时间", "updated_at": "记录更新时间", "version": "乐观锁版本号",
        },
    },
    "task_events": {
        "table": "任务事件日志表",
        "columns": {
            "id": "事件主键", "task_id": "所属任务主键", "level": "事件级别", "stage": "任务阶段",
            "message": "事件消息", "details_json": "事件详情JSON", "created_at": "事件创建时间",
        },
    },
    "task_resource_locks": {
        "table": "任务资源占用锁表",
        "columns": {
            "id": "锁记录主键", "resource_key": "被占用资源的哈希键", "task_id": "占用任务主键",
            "created_at": "锁创建时间",
        },
    },
    "app_settings": {
        "table": "应用设置表",
        "columns": {"key": "设置键", "value_json": "设置值JSON", "updated_at": "设置更新时间"},
    },
    "images": {
        "table": "图片身份主表",
        "columns": {
            "id": "图片主键", "kind": "图片业务类型", "original_filename": "原始文件名",
            "sha256": "文件SHA-256摘要", "pixel_digest": "规范化像素摘要",
            "width": "图片宽度像素", "height": "图片高度像素", "file_size": "文件字节大小",
            "status": "图片状态", "created_at": "记录创建时间", "updated_at": "记录更新时间",
        },
    },
    "image_files": {
        "table": "图片物理文件表",
        "columns": {
            "id": "文件记录主键", "image_id": "图片主键", "role": "文件业务角色", "path": "物理文件路径",
            "normalized_path_digest": "规范化路径摘要", "size_bytes": "文件字节大小",
            "mtime_ns": "文件修改时间纳秒值", "sha256": "文件SHA-256摘要",
            "file_status": "物理文件状态", "archive_date": "归档日期", "ratio_code": "生产比例编码",
            "created_at": "记录创建时间", "updated_at": "记录更新时间",
        },
    },
    "task_items": {
        "table": "任务图片明细表",
        "columns": {
            "id": "任务明细主键", "task_id": "所属任务主键", "image_id": "图片主键",
            "observed_path": "扫描时文件路径", "observed_path_digest": "扫描路径摘要",
            "stage": "图片处理阶段", "status": "图片处理状态", "error_code": "错误代码",
            "error_message": "错误消息", "snapshot_sha256": "冻结文件SHA-256摘要",
            "snapshot_size": "冻结文件字节大小", "snapshot_mtime_ns": "冻结文件修改时间纳秒值",
            "created_at": "记录创建时间", "updated_at": "记录更新时间",
        },
    },
    "file_operations": {
        "table": "文件安全操作审计表",
        "columns": {
            "id": "操作主键", "task_id": "所属任务主键", "task_item_id": "所属任务明细主键",
            "image_id": "图片主键", "operation": "操作类型", "origin_path": "源文件路径",
            "target_path": "目标文件路径", "origin_sha256": "源文件SHA-256摘要",
            "expected_size": "预期文件字节大小", "operation_key": "幂等操作键", "state": "操作执行状态",
            "reason": "操作原因", "thumbnail_path": "删除证据缩略图路径", "error_text": "操作错误详情",
            "created_at": "记录创建时间", "updated_at": "记录更新时间",
        },
    },
    "duplicate_pairs": {
        "table": "重复图片关系表",
        "columns": {
            "id": "重复关系主键", "task_id": "所属任务主键", "image_new_id": "本次新图片主键",
            "image_match_id": "匹配历史图片主键", "pair_type": "关系类型", "machine_decision": "机器判定结果",
            "rule_id": "判定规则标识", "evidence_json": "判定证据JSON", "review_required": "是否需要人工审核",
            "resolution_status": "关系处理状态", "created_at": "记录创建时间",
        },
    },
    "reviews": {
        "table": "人工审核表",
        "columns": {
            "id": "审核主键", "pair_id": "重复关系主键", "task_id": "所属任务主键", "status": "审核状态",
            "duplicate_decision": "人工重复判定", "action_decision": "人工操作决定", "note": "审核备注",
            "version": "乐观锁版本号", "created_at": "记录创建时间", "updated_at": "记录更新时间",
        },
    },
    "image_features": {
        "table": "图片向量特征表",
        "columns": {
            "id": "特征主键", "image_id": "图片主键", "feature_scope": "特征用途范围",
            "region_seq": "区域特征序号", "bbox_json": "区域边界框JSON", "model_id": "向量模型标识",
            "model_revision": "向量模型版本", "preprocess_version": "预处理版本", "dimension": "向量维度",
            "vector_blob": "原始float32向量二进制数据", "vector_sha256": "向量SHA-256摘要",
            "faiss_vector_id": "FAISS索引向量标识", "is_valid": "特征是否有效", "created_at": "记录创建时间",
        },
    },
    "vlm_calls": {
        "table": "视觉语言模型调用审计表",
        "columns": {
            "id": "调用主键", "task_id": "所属任务主键", "pair_id": "关联重复关系主键",
            "provider": "VLM服务提供方", "model": "VLM模型名称", "status": "调用状态",
            "request_metadata": "请求元数据JSON", "response_json": "结构化响应JSON",
            "error_code": "调用错误代码", "error_message": "调用错误消息", "created_at": "记录创建时间",
        },
    },
}


def apply_schema_comments(metadata: MetaData) -> None:
    """Attach comments to ORM metadata for tools that create a fresh schema."""
    for table_name, definition in TABLE_COMMENTS.items():
        table = metadata.tables.get(table_name)
        if table is None:
            continue
        table.comment = str(definition["table"])
        for column_name, comment in dict(definition["columns"]).items():
            table.c[column_name].comment = str(comment)
