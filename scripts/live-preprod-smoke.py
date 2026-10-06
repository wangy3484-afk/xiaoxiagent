"""Run one synthetic, real-provider report per operations scene in local preproduction.

The script never receives provider credentials. Supply them only to the deployed
API/Worker through the deployment environment. Output stays under .tmp/.
"""

import argparse
import asyncio
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.providers.http_fetcher import SecureHttpPageFetcher
from pydantic import HttpUrl


@dataclass(frozen=True)
class Scenario:
    scene: str
    context: str
    problem: str
    goal: str
    users: str
    stage: str
    period: str
    resources: str
    channels: tuple[str, ...]
    baseline: str
    constraints: tuple[str, ...]
    companies: tuple[str, ...]


SCENARIOS = (
    Scenario(
        "acquisition", "测试场景：区域生鲜小程序，以下数值均为虚构汇总数据",
        "新注册家庭用户的首单转化较低", "八周内验证有效新客首单增长路径",
        "两个门店片区的新注册家庭用户", "冷启动", "八周",
        "两名运营，实验预算上限五万元", ("门店社群", "本地生活内容"),
        "最近一个月新注册1000人，首单转化率8%", ("仅用汇总漏斗数据", "先覆盖两个片区"),
        ("京东", "淘宝"),
    ),
    Scenario(
        "retention", "测试场景：面向小团队的订阅协作工具，以下数值均为虚构汇总数据",
        "新用户配置后协作行为不足，首月流失较高", "九十天内改善新用户首月留存",
        "注册三十天内的小团队管理员", "增长期", "九十天",
        "两名运营及一名产品经理，可支持两轮实验", ("站内引导", "邮件"),
        "上月新注册500个团队，三十日留存率18%", ("先验证协作行为与留存关系", "触达要频控和退出"),
        ("滴滴", "京东"),
    ),
    Scenario(
        "campaign", "测试场景：社区零售节日活动，以下数值均为虚构汇总数据",
        "老客到店和线上复购不足", "三周活动提升符合条件老客的复购行为",
        "最近六十天有消费的社区老客", "稳定经营期", "三周",
        "三名运营，权益预算上限三万元，库存和客服有容量阈值", ("门店", "社群", "小程序"),
        "上月符合条件老客2000人，三十日复购率20%", ("必须防套利", "设置库存与客服降级预案"),
        ("淘宝", "京东"),
    ),
    Scenario(
        "content", "测试场景：本地家政服务内容运营，以下数值均为虚构汇总数据",
        "内容有浏览但有效咨询少", "九十天内建立可归因的内容到有效咨询路径",
        "首次考虑家政服务的本地家庭用户", "增长期", "九十天",
        "两名内容运营，内容制作预算上限两万元", ("小红书", "公众号", "自有网站"),
        "上月内容浏览10000次，有效咨询30次", ("只使用公开内容和匿名汇总数据", "不承诺咨询提升幅度"),
        ("小红书", "链家"),
    ),
)


def _field(value: str) -> BriefField[str]:
    return BriefField[str].from_user(value, value[:500])


def _list_field(values: tuple[str, ...]) -> BriefField[list[str]]:
    return BriefField[list[str]].from_user(list(values), "、".join(values)[:500])


def _brief(scenario: Scenario) -> OperationsBrief:
    return OperationsBrief(
        business_context=_field(scenario.context),
        current_problem=_field(scenario.problem),
        operation_goal=_field(scenario.goal),
        target_users=_field(scenario.users),
        business_stage=_field(scenario.stage),
        execution_period=_field(scenario.period),
        budget_and_resources=_field(scenario.resources),
        existing_channels=_list_field(scenario.channels),
        current_baseline=_field(scenario.baseline),
        constraints=_list_field(scenario.constraints),
        preferred_benchmark_companies=_list_field(scenario.companies),
    )


def _checked(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("unexpected API response")
    return payload


def _register(client: httpx.Client) -> None:
    account = {
        "email": f"smoke-{uuid4().hex}@example.invalid",
        "password": secrets.token_urlsafe(32),
    }
    _checked(client.post("/api/v1/auth/register", json=account))
    _checked(client.post("/api/v1/auth/login", json=account))


async def _open_original_evidence(report: dict[str, Any]) -> str | None:
    appendix = report.get("evidence_appendix", [])
    fetcher = SecureHttpPageFetcher(timeout_seconds=15, max_bytes=2_000_000, max_redirects=5)
    for item in appendix:
        url = item.get("url")
        if not isinstance(url, str):
            continue
        try:
            page = await fetcher.fetch(HttpUrl(url))
        except Exception:
            continue
        if 200 <= page.status_code < 400:
            return str(page.final_url)
    return None


def run_scene(
    client: httpx.Client, base_url: str, scenario: Scenario, output: Path
) -> dict[str, Any]:
    started = time.monotonic()
    created = _checked(
        client.post(
            "/api/v1/briefs",
            headers={"Idempotency-Key": f"live-brief-{uuid4().hex}"},
            json={
                "brief_payload": _brief(scenario).model_dump(mode="json"),
                "classification_payload": {
                    "primary_scene": scenario.scene,
                    "secondary_scenes": [],
                    "rationale": ["预发布测试人员指定的主运营场景"],
                    "confidence": 1.0,
                    "uncertainties": [],
                    "user_corrected": True,
                },
            },
        )
    )
    confirmed = _checked(
        client.post(
            f"/api/v1/briefs/{created['id']}/confirm",
            json={"expected_revision_number": created["latest_revision_number"]},
        )
    )
    job = _checked(
        client.post(
            "/api/v1/jobs",
            headers={"Idempotency-Key": f"live-job-{uuid4().hex}"},
            json={"brief_id": created["id"], "brief_revision_id": confirmed["revision_id"]},
        )
    )
    print(f"{scenario.scene}: job {job['id']} queued", flush=True)
    deadline = time.monotonic() + 900
    stage = None
    while time.monotonic() < deadline:
        current = _checked(client.get(f"/api/v1/jobs/{job['id']}"))
        if current["stage"] != stage:
            stage = current["stage"]
            print(f"{scenario.scene}: {current['status']} / {stage}", flush=True)
        if current["status"] in {"completed", "failed", "retryable"}:
            break
        time.sleep(5)
    else:
        raise TimeoutError(f"{scenario.scene}: report exceeded 900 seconds")

    result = {
        "scene": scenario.scene,
        "job_id": job["id"],
        "status": current["status"],
        "stage": current["stage"],
        "error_code": current.get("error_code"),
        "total_seconds": round(time.monotonic() - started, 2),
        "report_version_ids": current.get("report_version_ids", []),
    }
    if current["status"] == "completed" and current["report_version_ids"]:
        report_id = current["report_version_ids"][0]
        detail = _checked(client.get(f"/api/v1/reports/{report_id}"))
        report = detail["report_payload"]
        source_url = asyncio.run(_open_original_evidence(report))
        appendix = report.get("evidence_appendix", [])
        evidence_id = appendix[0]["evidence_id"] if appendix else None
        owner_evidence_status = (
            client.get(f"/api/v1/evidence/{evidence_id}").status_code
            if evidence_id is not None
            else None
        )
        with httpx.Client(base_url=base_url, verify=False, timeout=30, trust_env=False) as other:
            unauthenticated = other.get(f"/api/v1/reports/{report_id}").status_code
            anonymous_evidence = (
                other.get(f"/api/v1/evidence/{evidence_id}").status_code
                if evidence_id is not None
                else None
            )
            _register(other)
            unauthorized = other.get(f"/api/v1/reports/{report_id}").status_code
            other_user_evidence = (
                other.get(f"/api/v1/evidence/{evidence_id}").status_code
                if evidence_id is not None
                else None
            )
        result.update(
            {
                "report_id": report_id,
                "delivery_status": detail["delivery_status"],
                "evidence_count": len(report.get("evidence_appendix", [])),
                "opened_source_url": source_url,
                "anonymous_status": unauthenticated,
                "other_user_status": unauthorized,
                "owner_evidence_status": owner_evidence_status,
                "anonymous_evidence_status": anonymous_evidence,
                "other_user_evidence_status": other_user_evidence,
            }
        )
        (output / f"{scenario.scene}-report.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    (output / f"{scenario.scene}-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if result["status"] == "completed" and not (
        result.get("opened_source_url")
        and result.get("evidence_count", 0) >= 1
        and result.get("anonymous_status") == 401
        and result.get("other_user_status") == 404
        and result.get("owner_evidence_status") == 200
        and result.get("anonymous_evidence_status") == 401
        and result.get("other_user_evidence_status") == 404
    ):
        raise AssertionError(f"{scenario.scene}: report evidence or authorization check failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://localhost:18445")
    parser.add_argument("--scene", choices=[item.scene for item in SCENARIOS])
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("this smoke script only permits a local preproduction endpoint")
    output = Path(".tmp/acceptance-live-14-3")
    output.mkdir(parents=True, exist_ok=True)
    selected = [item for item in SCENARIOS if args.scene in (None, item.scene)]
    with httpx.Client(base_url=args.base_url, verify=False, timeout=120, trust_env=False) as client:
        _register(client)
        for scenario in selected:
            result = run_scene(client, args.base_url, scenario, output)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["status"] != "completed":
                raise RuntimeError(f"{scenario.scene}: report job did not complete")


if __name__ == "__main__":
    main()
