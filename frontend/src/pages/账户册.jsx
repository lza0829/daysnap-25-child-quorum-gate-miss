import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function 账户册() {
  const [行, set行] = useState([]);
  const [讯, set讯] = useState("");
  useEffect(() => {
    api.账户().then(set行).catch((e) => set讯(String(e.message || e)));
  }, []);
  return (
    <div>
      <h1 className="题">账户册</h1>
      <p className="述">种子账户。金额单位为分。父户镜由子户当日有效镜汇总，父键直接流水旁置。</p>
      {讯 ? <p className="讯">{讯}</p> : null}
      {!行.length ? (
        <div className="空态">暂无账户</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>账户键</th>
              <th>户名</th>
              <th>币种</th>
              <th>开户营业日</th>
              <th>状态</th>
              <th>父户键</th>
              <th>角色</th>
            </tr>
          </thead>
          <tbody>
            {行.map((r) => {
              const 是父 = 行.some((x) => x.父户键 === r.账户键);
              const 角色 = r.父户键 ? "子户" : 是父 ? "父户" : "普通户";
              return (
                <tr key={r.账户键}>
                  <td>{r.账户键}</td>
                  <td>{r.户名}</td>
                  <td>{r.币种}</td>
                  <td>{r.开户营业日}</td>
                  <td>{r.状态}</td>
                  <td>{r.父户键 || "—"}</td>
                  <td>
                    <span className={`徽章 ${角色 === "普通户" ? "" : "通"}`}>{角色}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
