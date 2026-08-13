import { useEffect, useState } from "react";
import { get } from "../api";

type ProductHealth = {
  ok?: boolean;
  warnings?: string[];
  checks?: Record<string, boolean>;
  dependencies?: Record<string, boolean>;
  data?: { database?: { works?: number }; images?: { files?: number }; generated?: { files?: number } };
  git?: { dirty?: boolean; changed_files?: number; message?: string };
};

type ProductStrategy = {
  name?: string;
  one_liner?: string;
  positioning?: string;
  target_user?: string;
  core_loop?: string[];
};

type Verification = {
  acceptance?: string[];
  commands?: string[];
  manual_urls?: string[];
};

export function OpsPage() {
  const [health, setHealth] = useState<ProductHealth | null>(null);
  const [strategy, setStrategy] = useState<ProductStrategy | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    get<{ health?: ProductHealth }>("/api/product/health")
      .then((payload) => setHealth(payload.health || null))
      .catch((err: Error) => setError(err.message));
    get<{ strategy?: ProductStrategy }>("/api/product/strategy")
      .then((payload) => setStrategy(payload.strategy || null))
      .catch((err: Error) => setError(err.message));
    get<{ verification?: Verification }>("/api/product/verification")
      .then((payload) => setVerification(payload.verification || null))
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <section className="ws-panel">
      <h2>运营</h2>
      <p className="ws-status">只读本机健康检查，不会改配置、不会出图、不会扣 Anlas。</p>
      {strategy ? (
        <>
          <h3>{strategy.name || "产品定位"}</h3>
          <p className="ws-prompt">{strategy.one_liner || strategy.positioning}</p>
          <p className="ws-status">{strategy.target_user}</p>
          <ul className="ws-list">
            {(strategy.core_loop || []).map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>健康 {health?.ok ? "通过" : "有缺口"}</h3>
      <ul className="ws-list">
        {Object.entries(health?.checks || {}).map(([key, ok]) => (
          <li key={key}>
            {key} · {ok ? "OK" : "缺失"}
          </li>
        ))}
      </ul>
      <ul className="ws-list">
        {Object.entries(health?.dependencies || {}).map(([key, ok]) => (
          <li key={key}>
            {key} · {ok ? "已安装" : "未安装"}
          </li>
        ))}
      </ul>
      {(health?.warnings || []).map((warning) => (
        <p key={warning} className="ws-status err">
          {warning}
        </p>
      ))}
      {health?.git?.dirty ? (
        <p className="ws-status">Git 未提交文件 {health.git.changed_files || 0} 个。</p>
      ) : null}
      <h3>验收清单</h3>
      <ul className="ws-list">
        {(verification?.acceptance || []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {error ? <p className="ws-status err">{error}</p> : null}
    </section>
  );
}
