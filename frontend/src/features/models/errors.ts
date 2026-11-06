const messages: Record<string, string> = {
  MODEL_AUTH_FAILED: "认证或访问权限失败，请检查已保存凭据和该模型的访问权限。",
  MODEL_NOT_CONFIGURED: "请在设置中配置模型并保存凭据。",
  SECRET_STORE_UNAVAILABLE: "系统凭据库不可用，请检查本机凭据服务。",
  MODEL_CONNECTION_FAILED: "模型连接失败，请检查配置地址和连接情况。",
  MODEL_TIMEOUT: "模型请求超时，请稍后重试或检查服务状态。",
  MODEL_PAYMENT_REQUIRED: "供应商返回 HTTP 402，请在供应商后台核对账户和计费状态。",
  MODEL_NOT_FOUND: "供应商返回 HTTP 404，请核对模型名称和 API 路由。",
  MODEL_RATE_LIMITED: "供应商限制请求频率（429），请稍后重试。",
  MODEL_SERVER_ERROR: "供应商服务端错误（5xx），请稍后重试。",
  MODEL_HTTP_ERROR: "模型服务返回其他 HTTP 错误，请检查服务与配置。",
  MODEL_PROTOCOL_UNSUPPORTED: "模型不支持当前请求协议，请核对服务能力。",
  MODEL_ACTION_INVALID: "模型返回的动作格式无效，请重新发送；反复发生时核对工具调用能力。",
  MODEL_OUTPUT_INVALID: "模型输出未通过校验，请重新发送或核对结构化输出能力。",
  MODEL_INTERNAL_ERROR: "模型调用出现内部异常，请保留错误码供诊断后重试。",
  MODEL_UNAVAILABLE: "历史故障原因尚未定位，请检查后续请求的诊断结果。",
  EVIDENCE_STALE: "原文证据已删除或版本已变，请重新检索。",
};

export const modelFailure = (code?: string | null): string =>
  `运行失败：${code || "UNKNOWN_ERROR"}（${messages[code ?? ""] ?? "请核对配置和证据后重试。"}）`;
