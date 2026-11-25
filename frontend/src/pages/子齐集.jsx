import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api.js";

function 徽({ ok, children }) {
  return <span className={`徽章 ${ok ? "通" : "败"}`}>{children}</span>;
}

function 列表({ value }) {
  if (!value || !value.length) return "—";
  return value.join("、");
}

export default function 核证子齐集() {
  const [search, setSearch] = useSearchParams();
  const qFromUrl = search.get("齐集号") || search.get("quorum_no") || "";
  const keyFromUrl = search.get("键") || "";
  const [rows, setRows] = useState([]);
  const [scene, setScene] = useState(null);
  const [qid, setQid] = useState(qFromUrl || keyFromUrl);
  const [parent, setParent] = useState(search.get("父键") || "");
  const [day, setDay] = useState(search.get("营业日") || "");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const loadList = async () => {
    const data = await api.子齐集核证();
    setRows(data.齐集 || data || []);
    return data;
  };

  const openScene = async (id, extras = {}) => {
    setErr("");
    setMsg("");
    try {
      const params = new URLSearchParams();
      if (id) {
        if (extras.asKey) params.set("键", id);
        else params.set("齐集号", id);
      }
      if (extras.parent) params.set("父键", extras.parent);
      if (extras.day) params.set("营业日", extras.day);
      setSearch(params);
      const qs = params.toString();
      const data = await api.子齐集核证(qs);
      setScene(data);
      if (data.齐集号) setQid(data.齐集号);
      await loadList();
    } catch (e) {
      setErr(String(e.message || e));
    }
  };

  useEffect(() => {
    loadList()
      .then(() => {
        if (qFromUrl) return openScene(qFromUrl);
        if (keyFromUrl) return openScene(keyFromUrl, { asKey: true });
        setScene(null);
      })
      .catch((e) => setErr(String(e.message || e)));
    // URL 是台面、父镜页和核证接口共享的现场入口。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qFromUrl, keyFromUrl]);

  const queryByParent = async () => {
    const params = new URLSearchParams();
    if (parent) params.set("父键", parent);
    if (day) params.set("营业日", day);
    await openScene("", { parent, day });
    setSearch(params);
  };

  const promote = async () => {
    if (!scene?.齐集号) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      const r = await api.齐集晋升({ 齐集号: scene.齐集号 });
      setMsg(`已显式晋升：${r.齐集号}，父余额 ${r.父正式?.余额 ?? "—"}`);
      await openScene(r.齐集号);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  const markSuccess = async () => {
    if (!scene?.齐集号) return;
    setBusy(true);
    setErr("");
    setMsg("");
    try {
      await api.齐集标记父成功({ 齐集号: scene.齐集号, 父成功: true, aligned: true });
      setMsg("标记请求已核库放行。");
      await openScene(scene.齐集号);
    } catch (e) {
      setErr(`失败闭（符合预期）：${String(e.message || e)}`);
      await openScene(scene.齐集号);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <h1 className="题">子齐集核证</h1>
      <p className="述">
        齐集号贯穿父抽、子抽、回放与差额。当前落实乙案：应收≠实收时只允许非权威旁置父镜，
        正式有效父镜禁写；补齐子户后必须显式晋升。
      </p>

      <div className="行">
        <input
          style={{ minWidth: 280 }}
          value={qid}
          onChange={(e) => setQid(e.target.value)}
          placeholder="输入齐集号，如 齐集-户汇总-2026-12-11"
        />
        <button onClick={() => openScene(qid)}>按齐集号打开同一缺子现场</button>
        <input value={parent} onChange={(e) => setParent(e.target.value)} placeholder="父键" />
        <input value={day} onChange={(e) => setDay(e.target.value)} placeholder="YYYY-MM-DD" />
        <button className="次" onClick={queryByParent}>按父键/营业日核证</button>
        <button className="次" onClick={loadList}>刷新列表</button>
      </div>

      {msg ? <p className="讯">{msg}</p> : null}
      {err ? <pre className="码" style={{ whiteSpace: "pre-wrap" }}>{err}</pre> : null}

      {scene ? (
        <div className="提示条" data-testid="齐集现场">
          <div className="行" style={{ marginBottom: 8 }}>
            <b data-testid="齐集号">{scene.齐集号 || "—"}</b>
            <span>{scene.父键}</span>
            <span>{scene.营业日}</span>
            <徽 ok={scene.valid}>{scene.valid ? "valid=true" : "valid=false"}</徽>
            <徽 ok={scene.父正式有无}>{scene.父正式有无 ? "有正式父镜" : "无正式有效父镜"}</徽>
            <徽 ok={scene.旁置有无}>{scene.旁置有无 ? "有活跃旁置" : "无活跃旁置"}</徽>
            {scene.已满 ? <徽 ok={true}>齐集已满</徽> : <徽 ok={false}>齐集未满</徽>}
          </div>
          <div>应收子集合（{scene.应收数 ?? scene.应收?.length ?? 0}）：<列表 value={scene.应收} /></div>
          <div>实收集合（{scene.实收数 ?? scene.实收?.length ?? 0}）：<列表 value={scene.实收} /></div>
          <div data-testid="缺子列表">缺子列表：<b><列表 value={scene.缺子列表} /></b></div>
          <div>旁置号：{scene.旁置号 || "—"}　原因：{scene.原因 || "—"}</div>
          <div className="行" style={{ marginTop: 8 }}>
            <button disabled={busy || !scene.已满 || scene.valid} onClick={promote}>
              显式晋升旁置
            </button>
            <button className="次" disabled={busy || !scene.齐集号} onClick={markSuccess}>
              故意未满却标父成功（须失败闭）
            </button>
            <Link className="次" to={`/父镜?齐集号=${encodeURIComponent(scene.齐集号 || "")}&营业日=${encodeURIComponent(scene.营业日 || "")}`}>
              到父镜页查看
            </Link>
          </div>
          <pre className="码" style={{ marginTop: 10, maxHeight: 280, overflow: "auto" }}>
            {JSON.stringify(scene, null, 2)}
          </pre>
        </div>
      ) : (
        <div className="空态">选择下方齐集行，或输入齐集号打开现场。</div>
      )}

      <div className="段">
        <h2 className="段题">最近齐集行</h2>
        {!rows.length ? (
          <div className="空态">暂无齐集行；先在父镜页或日终抽取中跑缺子夹具。</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>齐集号</th><th>父键</th><th>营业日</th><th>状态</th>
                <th>缺子</th><th>旁置</th><th>正式镜</th><th>valid</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.齐集号 || r.编号}>
                  <td><code>{r.齐集号}</code></td>
                  <td>{r.父键}</td>
                  <td>{r.营业日}</td>
                  <td>{r.状态}</td>
                  <td><列表 value={r.缺子列表 || r.缺子} /></td>
                  <td>{r.旁置有无 ? "有" : "—"}</td>
                  <td>{r.父正式有无 ? "有" : "无"}</td>
                  <td>{String(r.valid)}</td>
                  <td><button className="次" onClick={() => openScene(r.齐集号)}>打开</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
