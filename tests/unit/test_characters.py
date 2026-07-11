"""
test_characters.py — P1 角色卡 JSON schema 校验

门控: P1 commit 前必须 pytest PASS
策略: 简单 dict 校验 (P5 types.py 才上 Pydantic, P1 只验 JSON 合法 + 必填字段)
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

CHARACTERS_DIR = Path("data/characters")


def _load(name: str) -> dict:
    path = CHARACTERS_DIR / name
    assert path.exists(), f"missing: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


# ============================================================
# youkei.json — 猫角色卡
# ============================================================


class TestYoukei:
    def test_load(self):
        d = _load("youkei.json")
        assert isinstance(d, dict)

    def test_required_fields(self):
        d = _load("youkei.json")
        required = ["name", "species", "age_months", "gender", "appearance", "personality", "habits"]
        for field in required:
            assert field in d, f"youkei.json 缺必填字段: {field}"

    def test_name_is_youkei(self):
        d = _load("youkei.json")
        assert d["name"] == "YouKei", f"猫名必须是 YouKei (老板 21:36 拍板), 实为 {d['name']}"

    def test_appearance_required(self):
        d = _load("youkei.json")
        app = d["appearance"]
        for k in ["毛色", "眼睛", "体型", "特征"]:
            assert k in app, f"appearance 缺字段: {k}"

    def test_age_within_range(self):
        """7 月龄合理 (3-12 月)"""
        d = _load("youkei.json")
        assert 3 <= d["age_months"] <= 12, f"age_months 应 3-12, 实为 {d['age_months']}"

    def test_habits_has_4_periods(self):
        d = _load("youkei.json")
        habits = d["habits"]
        for period in ["晨", "午", "晚", "夜"]:
            assert period in habits, f"habits 缺时间段: {period}"

    def test_forbidden_non_empty(self):
        d = _load("youkei.json")
        assert len(d["forbidden"]) > 0, "forbidden 不能为空"


# ============================================================
# protagonist.json — 主角角色卡
# ============================================================


class TestProtagonist:
    def test_load(self):
        d = _load("protagonist.json")
        assert isinstance(d, dict)

    def test_required_fields(self):
        d = _load("protagonist.json")
        required = [
            "name", "real_name_protected", "gender",
            "appearance_visible", "appearance_hidden",
            "personality", "speaking_style",
            "forbidden", "signature_moves",
        ]
        for field in required:
            assert field in d, f"protagonist.json 缺必填字段: {field}"

    def test_name_is_shangkun(self):
        """老板拍板化名"上坤" (Q1)"""
        d = _load("protagonist.json")
        assert d["name"] == "上坤", f"主角名必须是 '上坤', 实为 {d['name']}"

    def test_real_name_protected_true(self):
        """真名不可暴露 (Q1 老板决策)"""
        d = _load("protagonist.json")
        assert d["real_name_protected"] is True

    def test_appearance_visible_no_face(self):
        """Q1: 只出手+配音, 露脸后期 (老板决策)"""
        d = _load("protagonist.json")
        visible = d["appearance_visible"]
        assert "❌" in visible["face"], f"face 必须明确不露正脸: {visible['face']}"
        assert "✅" in visible["hands"], "hands 必须可露"
        assert "✅" in visible["voice"], "voice 必须可配音"

    def test_forbidden_includes_face(self):
        """forbidden 列表必须包含 '露正脸'"""
        d = _load("protagonist.json")
        forbidden_str = " ".join(d["forbidden"])
        assert "正脸" in forbidden_str, "forbidden 必须包含 '露正脸'"

    def test_speaking_style_short_sentences(self):
        d = _load("protagonist.json")
        assert d["speaking_style"]["sentence_length"].startswith("短句为主")

    def test_no_swear(self):
        d = _load("protagonist.json")
        assert d["speaking_style"]["no_swear"] == "❌ 不说脏话 / 不爆粗口"


# ============================================================
# apartment.json — 公寓场景卡
# ============================================================


class TestApartment:
    def test_load(self):
        d = _load("apartment.json")
        assert isinstance(d, dict)

    def test_required_fields(self):
        d = _load("apartment.json")
        required = ["name", "layout", "outdoor_locations", "props_for_story"]
        for field in required:
            assert field in d, f"apartment.json 缺必填字段: {field}"

    def test_layout_has_6_rooms(self):
        """60 平小两居: 6 室 (主卧/次卧/客厅/厨房/卫生间/阳台)"""
        d = _load("apartment.json")
        layout = d["layout"]
        required_rooms = ["客厅", "主卧", "次卧", "厨房", "卫生间", "阳台"]
        for room in required_rooms:
            assert room in layout, f"layout 缺房间: {room}"

    def test_outdoor_has_5_locations(self):
        d = _load("apartment.json")
        outdoor = d["outdoor_locations"]
        assert len(outdoor) >= 5, f"外出备选应 ≥5 个, 实为 {len(outdoor)}"

    def test_balcony_safety_warning(self):
        """阳台安全警告 (猫不可爬护栏外侧)"""
        d = _load("apartment.json")
        balcony = d["layout"]["阳台"]
        assert "safety_warning" in balcony, "阳台必须含 safety_warning"
        assert "❌" in balcony["safety_warning"]

    def test_apartment_forbidden_includes_address(self):
        """不可暴露地址/街景"""
        d = _load("apartment.json")
        forbidden = " ".join(d["forbidden_in_apartment"])
        assert "街景" in forbidden or "门牌号" in forbidden

    def test_time_of_day_periods(self):
        d = _load("apartment.json")
        prefs = d["time_of_day_preferences"]
        for period in ["morning", "noon", "afternoon", "evening", "night"]:
            assert period in prefs, f"time_of_day_preferences 缺: {period}"


# ============================================================
# 跨卡一致性
# ============================================================


class TestCrossCharacterConsistency:
    def test_all_3_files_exist(self):
        for name in ["youkei.json", "protagonist.json", "apartment.json"]:
            path = CHARACTERS_DIR / name
            assert path.exists(), f"missing: {path}"

    def test_protagonist_relationship_mentions_youkei(self):
        d = _load("protagonist.json")
        rel = d["relationship_with_youkei"]
        assert "style" in rel
        assert "talking_to_cat" in rel
        assert "boundary" in rel

    def test_youkei_vocabulary_distinct(self):
        """猫不能说话, 只能 '喵/咔/嘶'"""
        d = _load("youkei.json")
        vocab = d["vocabulary"]
        # 至少 4 种情绪的声音
        assert len(vocab) >= 4

    def test_protagonist_forbidden_more_than_5(self):
        """主角必须 ≥5 条红线 (隐私 + 内容 + 拍摄)"""
        d = _load("protagonist.json")
        assert len(d["forbidden"]) >= 5, f"forbidden 应 ≥5, 实为 {len(d['forbidden'])}"