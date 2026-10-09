"""注明来源与适用边界的帮助内容。"""
EXPERT_GUIDES = {
    "proxy_config":{"title":"代理配置与实际连接","summary":"区分配置存在、代理可用与目标应用实际采用。",
        "content":"""### 配置与运行是不同证据
检测当前进程继承环境和用户级 Claude 设置；其他项目、组织托管设置及已运行会话可能不同。
修复只写入用户级 settings.json 的 env，保留其他设置，不改 Windows 全局变量。现有会话需要重启读取配置。
没有 TUN 不等于应用代理失效；看到网卡也不证明全局路由生效。
[Claude Code 官方网络配置](https://code.claude.com/docs/en/network-config)
"""},
    "test_limits":{"title":"检测结果如何理解","summary":"配置参考评分不是封号概率。",
        "content":"""### 只展示能证明的结论
出口查询只证明该请求经过指定代理。IP 地理信息不能证明住宅、独享或信誉。
DNS 配置与一次 DoH 成功不能证明没有泄漏，需要另行验证实际路由。
时区展示本机实际值，不判断账号安全。地区资格不能通过更换时区或出口自动取得。
[Anthropic 支持地区政策](https://www.anthropic.com/supported-countries)
"""},
    "snapshots":{"title":"快照与还原","summary":"逐次保存，发生外部变化时停止覆盖。",
        "content":"""### 还原边界
新版本逐次保存快照；备份失败停止修改。配置还原核对写入后的摘要，避免覆盖后来的更改。
旧版快照仅供查看，自动还原被禁用。旧测试写入的端口不能作为原始值。
缓存移动到隔离目录，不永久删除；原位置已生成新缓存时停止还原。
还原成功表示设置或目录核对通过，不代表客户端效果或开机行为已验证。
"""},
    "windows_release":{"title":"Windows 权限与发布","summary":"普通权限检测，不要求关闭 Defender。",
        "content":"""### 发布到其他电脑
默认普通用户权限。不修改 Defender、SmartScreen 或杀毒排除项。
原生 API 不能保证零误报；签名、文件信誉和杀毒检测是不同因素。代码签名也不保证首次运行不提示。
[微软 SmartScreen 发布信誉说明](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
### 账号申诉
通过官方支持入口核对流程，按真实情况说明时间、错误和账号信息，不编造出差、企业网络或所在地。
"""}
}


class ExpertGuideManager:
    @staticmethod
    def get_all_guides():
        return [{"id":key,**value,"content":value["content"].strip()} for key,value in EXPERT_GUIDES.items()]

    @staticmethod
    def get_guide_by_id(guide_id):
        return EXPERT_GUIDES.get(guide_id,{})
