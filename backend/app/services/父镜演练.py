"""父镜夹具演练：把静态夹具串成可执行的端到端链路。

支持三类夹具（按文件内字段自动识别）：
- 含 `账户配置` + `流水`：配置父子 -> 装载 -> 按流水营业日依次抽取。
- 含 `篡改`：按 `篡改` 直接改库子快照，再返回父主读与核证对照。
- 含 `并发抽取`：同一天用多线程并发抽取，校验父子同批、无父成功子缺日。
"""

import json
import threading
from typing import Any

from app.db import 夹具目录, 连接
from app.modules import 子户汇总镜
from app.services import 抽取, 回放
from app.services.装载 import 装载流水


def _读夹具(名: str) -> dict[str, Any]:
    path = 夹具目录 / 名
    if not path.exists():
        raise FileNotFoundError(f"夹具不存在: {名}")
    return json.loads(path.read_text(encoding="utf-8"))


def _配置(项: list[dict]) -> list[dict]:
    结果 = []
    for x in 项 or []:
        try:
            结果.append(子户汇总镜.配置父户(str(x["子户键"]), str(x["父户键"])))
        except 子户汇总镜.配置异常 as e:
            结果.append({"子户键": x.get("子户键"), "错误": str(e)})
    return 结果


def _取父户(闩: dict[str, Any]) -> str:
    if 闩.get("父户键"):
        return str(闩["父户键"])
    for x in 闩.get("账户配置") or []:
        if x.get("父户键"):
            return str(x["父户键"])
    return "户汇总"


def 演练(名: str) -> dict[str, Any]:
    闩 = _读夹具(名)
    报告: dict[str, Any] = {"夹具": 名, "说明": 闩.get("说明", ""), "步骤": []}

    
    
    篡改父户 = str(闩.get("父户键") or "")
    篡改日 = str(闩.get("营业日") or "")
    仅篡改 = (
        bool(闩.get("篡改"))
        and not 闩.get("并发抽取")
        and bool(篡改父户)
        and 子户汇总镜.读取父镜(篡改父户, 篡改日) is not None
    )

    if 仅篡改:
        报告["步骤"].append(
            {"说明": "父镜已固化，跳过配置/装载/抽取，仅执行篡改对照"}
        )
    else:
        if 闩.get("账户配置"):
            报告["步骤"].append({"配置": _配置(闩["账户配置"])})

        if 闩.get("流水"):
            报告["步骤"].append({"装载": 装载流水(闩["流水"], str(闩.get("批次编号") or ""))})

        
        流水日们 = sorted(
            {str(x.get("营业日")) for x in 闩.get("流水") or [] if x.get("营业日")}
        )
        if 流水日们 and not 闩.get("并发抽取"):
            抽取结果 = []
            for 日 in 流水日们:
                try:
                    抽取结果.append(抽取.日终抽取(日))
                except 子户汇总镜.缺子异常 as e:
                    抽取结果.append({"营业日": 日, "错误": "父镜未成·缺子", "缺子": e.缺子})
                    报告["步骤"].append({"抽取": 抽取结果})
                    报告["失败"] = "父镜未成·缺子"
                    return 报告
            报告["步骤"].append({"抽取": 抽取结果})

    if 闩.get("并发抽取"):
        日 = str(闩.get("营业日") or "")
        结果: list[dict] = []
        错误: list[str] = []

        def 跑(批: str):
            try:
                结果.append(抽取.日终抽取(日, 批))
            except Exception as e:  
                错误.append(str(e))

        线程们 = [threading.Thread(target=跑, args=(批,)) for 批 in 闩["并发抽取"]]
        for t in 线程们:
            t.start()
        for t in 线程们:
            t.join()
        父户 = _取父户(闩)
        父镜 = 子户汇总镜.读取父镜(父户, 日)
        核 = 子户汇总镜.核证(父户, 日)
        批集 = {x["批次编号"] for x in 结果}
        同批 = bool(父镜) and 父镜.get("抽取批次编号") in 批集 and all(
            x.get("抽取批次编号") == 父镜.get("抽取批次编号")
            for x in (父镜 or {}).get("子集合", [])
        )
        报告["步骤"].append(
            {
                "并发抽取": {
                    "营业日": 日,
                    "批次数": len(结果),
                    "错误": 错误,
                    "父镜": 父镜,
                    "父子同批": 同批,
                    "核证valid": 核.get("valid"),
                }
            }
        )

    if 闩.get("篡改"):
        父户 = str(闩.get("父户键") or _取父户(闩))
        日 = str(闩.get("营业日") or "")
        前主读 = 子户汇总镜.读取父镜(父户, 日)
        前核 = 子户汇总镜.核证(父户, 日)
        if 前主读 is None:
            报告["步骤"].append(
                {
                    "篡改子镜": {
                        "跳过": True,
                        "原因": f"父镜未固化：{父户} {日}（请先执行父子汇总样例）",
                    }
                }
            )
        else:
            conn = 连接()
            try:
                for x in 闩["篡改"]:
                    conn.execute(
                        "UPDATE 周期快照 SET 余额=? WHERE 账户键=? AND 营业日=?",
                        (int(x["新余额"]), str(x["账户键"]), str(x["营业日"])),
                    )
                conn.commit()
            finally:
                conn.close()
            后主读 = 子户汇总镜.读取父镜(父户, 日)
            后核 = 子户汇总镜.核证(父户, 日)
            报告["步骤"].append(
                {
                    "篡改子镜": {
                        "父户键": 父户,
                        "营业日": 日,
                        "前主读余额": 前主读["余额"],
                        "后主读余额": 后主读["余额"],
                        "主读不变": 前主读["余额"] == 后主读["余额"],
                        "前valid": 前核.get("valid"),
                        "后valid": 后核.get("valid"),
                        "后指纹匹配": 后核.get("指纹匹配"),
                        "后失配子": 后核.get("失配子"),
                        "现场重算余额": 后核.get("现场重算余额"),
                    }
                }
            )

    
    日们 = sorted({str(x.get("营业日")) for x in 闩.get("流水") or [] if x.get("营业日")})
    if 日们:
        try:
            报告["步骤"].append({"回放": 回放.回放核对(日们[-1])})
        except Exception as e:  
            报告["步骤"].append({"回放错误": str(e)})

    return 报告
