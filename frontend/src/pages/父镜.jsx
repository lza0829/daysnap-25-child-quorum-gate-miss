import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const 默认日 = "2026-11-20";

function 徽({ 通, 文 }) {
  return <span className={`徽章 ${通 ? "通" : "败"}`}>{文 || (通 ? "匹配" : "失配")}</span>;
}

export default function 父镜() {
  const [行, set行] = useState([]);
  const [账户, set账户] = useState([]);
  const [日, set日] = useState(默认日);
  const [父户键, set父户键] = useState("户汇总");
  const [核, set核] = useState(null);
  const [讯, set讯] = useState("");
  const [仿真, set仿真] = useState(null);
  const [子, set子] = useState("户子甲");
  const [父, set父] = useState("户汇总");
  const [夹具, set夹具] = useState([]);
  const [选夹, set选夹] = useState("父子汇总样例.json");

  const 刷新 = async () => {
    set行(await api.父镜());
    set账户(await api.账户());
    set夹具(await api.夹具());
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 核证 = async () => {
    set讯("");
    try {
      const r = await api.父镜核证(父户键, 日);
      set核(r);
      if (!r.找到) set讯("该父户当日尚未固化，先抽取或重汇总。");
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 重汇总 = async () => {
    set讯("");
    try {
      const r = await api.父镜重汇总(父户键, 日);
      set讯(`重汇总 ${r.账户键} ${r.营业日}：${r.前余额 ?? "—"} → ${r.余额}，指纹 ${r.汇总指纹.slice(0, 12)}…`);
      await 刷新();
      await 核证();
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 演练 = async (重置) => {
    set讯("");
    set仿真(null);
    try {
      if (重置) await api.重置();
      const r = await api.父镜演练(选夹);
      set仿真(r);
      set讯(`演练完成：${选夹}`);
      await 刷新();
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 配父 = async () => {
    set讯("");
    try {
      const r = await api.父镜配置(子, 父);
      set讯(`已把 ${r.子户键} 挂到 ${r.父户键}；父键流水旁置 ${r.父键流水旁置} 笔`);
      await 刷新();
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 解绑 = async (子户键) => {
    set讯("");
    try {
      const r = await api.父镜解绑(子户键);
      set讯(r.已解绑 ? `已解绑 ${子户键}（原父 ${r.原父户键}）` : `${子户键} 原本无父户`);
      await 刷新();
    } catch (e) {
      set讯(String(e.message || e));
    }
  };

  const 父户们 = 账户.filter((a) => 账户.some((b) => b.父户键 === a.账户键));
  const 子户们 = 账户.filter((a) => a.父户键);

  return (
    <div>
      <h1 className="题">子户汇总镜</h1>
      <p className="述">
        父户日终有效镜 = 子户当日有效镜汇总并固化指纹。父对外主读只读固化行，不 JOIN 子表；
        篡改子快照后主读不变、核证报指纹失配，只有显式重汇总才刷新。父键直接流水一律旁置。
      </p>

      <div className="行">
        <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" />
        <select value={父户键} onChange={(e) => set父户键(e.target.value)}>
          {(父户们.length ? 父户们 : [{ 账户键: "户汇总" }]).map((a) => (
            <option key={a.账户键} value={a.账户键}>{a.账户键}</option>
          ))}
        </select>
        <button className="次" onClick={核证}>核证（只读）</button>
        <button onClick={重汇总}>显式重汇总</button>
        <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
      </div>
      {讯 ? <p className="讯">{讯}</p> : null}

      {核 ? (
        <div className="提示条">
          <div className="行" style={{ marginBottom: 6 }}>
            <b>{核.账户键}</b>
            <span>{核.营业日}</span>
            <徽 通={核.valid} 文={核.valid ? "核证通过" : "核证未通过"} />
            {核.原因 ? <span>· {核.原因}</span> : null}
          </div>
          <div>固化余额 <b>{核.固化余额 ?? "—"}</b>　现场重算 <b>{核.现场重算余额 ?? "—"}</b>　余额匹配 <徽 通={核.余额匹配} /></div>
          <div>固化指纹 <code>{核.固化指纹 || "—"}</code></div>
          <div>现场指纹 <code>{核.现场指纹 || "—"}</code></div>
          <div>指纹匹配 <徽 通={核.指纹匹配} />　子集变化 {String(核.子集变化)}
            {核.缺子?.length ? `　缺子：${核.缺子.join("、")}` : ""}
            {核.失配子?.length ? `　失配子：${核.失配子.join("、")}` : ""}
          </div>
        </div>
      ) : null}

      <div className="段">
        <h2 className="段题">父镜固化行（对外主读）</h2>
        {!行.length ? (
          <div className="空态">暂无父镜固化行</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>父户键</th>
                <th>营业日</th>
                <th>余额</th>
                <th>子户数</th>
                <th>汇总指纹</th>
                <th>批次</th>
                <th>来源</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {行.map((r) => (
                <tr key={r.快照键}>
                  <td>{r.账户键}</td>
                  <td>{r.营业日}</td>
                  <td>{r.余额}</td>
                  <td>{r.子户数}</td>
                  <td><code>{String(r.汇总指纹 || "").slice(0, 16)}…</code></td>
                  <td>{r.抽取批次编号}</td>
                  <td>{r.来源}</td>
                  <td>{r.状态}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">父子配置（仅单层）</h2>
        <div className="行">
          <select value={子} onChange={(e) => set子(e.target.value)}>
            {账户.map((a) => (
              <option key={a.账户键} value={a.账户键}>{a.账户键}</option>
            ))}
          </select>
          <span>→</span>
          <select value={父} onChange={(e) => set父(e.target.value)}>
            {账户.map((a) => (
              <option key={a.账户键} value={a.账户键}>{a.账户键}</option>
            ))}
          </select>
          <button onClick={配父}>挂为子户</button>
        </div>
        {!子户们.length ? (
          <div className="空态">暂无子户</div>
        ) : (
          <table>
            <thead><tr><th>子户键</th><th>父户键</th><th>操作</th></tr></thead>
            <tbody>
              {子户们.map((a) => (
                <tr key={a.账户键}>
                  <td>{a.账户键}</td>
                  <td>{a.父户键}</td>
                  <td><button className="次" onClick={() => 解绑(a.账户键)}>解绑</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">夹具演练</h2>
        <div className="行">
          <select value={选夹} onChange={(e) => set选夹(e.target.value)}>
            {夹具.filter((n) => n.includes("父") || n.includes("篡改")).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <button onClick={() => 演练(true)}>重置并演练</button>
          <button className="次" onClick={() => 演练(false)}>直接演练</button>
        </div>
        {仿真 ? (
          <pre style={{ background: "var(--块)", border: "1px solid var(--线)", borderRadius: 10, padding: "0.8rem", overflowX: "auto", fontSize: "0.78rem" }}>
            {JSON.stringify(仿真, null, 2)}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
