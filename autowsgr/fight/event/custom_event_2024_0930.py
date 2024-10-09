"""舰队问答类活动抄这个
后续做活动地图时截取简单活动页面，放在event_image，出击按钮为1.png，简单活动页面是2.png
"""

import copy
import os
import time
from abc import ABC, abstractmethod

from autowsgr.constants import literals
from autowsgr.constants.custom_exceptions import ImageNotFoundErr, NetworkErr
from autowsgr.constants.image_templates import IMG
from autowsgr.constants.other_constants import ALL_SHIP_TYPES, SAP
from autowsgr.constants.positions import BLOOD_BAR_POSITION
from autowsgr.constants.ui import Node
from autowsgr.game.expedition import Expedition
from autowsgr.game.game_operation import (
    DestroyShip,
    click_result,
    detect_ship_stats,
    get_ship,
    match_night,
)
from autowsgr.game.get_game_info import detect_ship_stats, get_enemy_condition
from autowsgr.port.ship import Fleet
from autowsgr.timer import Timer
from autowsgr.utils.io import recursive_dict_update, yaml_to_dict
from autowsgr.utils.math_functions import get_nearest, CalcDis

from autowsgr.constants.positions import FIGHT_CONDITIONS_POSITION
from autowsgr.game.game_operation import ChangeShips, MoveTeam, quick_repair, SetAutoSupply

from autowsgr.constants.data_roots import MAP_ROOT
from autowsgr.fight.event.event import Event
from autowsgr.fight.normal_fight import NormalFightInfo, NormalFightPlan

NODE_POSITION = (
    None,
    (0.266, 0.196),
    (0.135, 0.559),
    (0.535, 0.765),
    (0.718, 0.316),
    (0.851, 0.671),
)

def start_march(timer: Timer, position=(900, 500)):
    timer.click(*position, 1, delay=0)
    start_time = time.time()
    while timer.identify_page("fight_prepare_page"):
        if time.time() - start_time > 3:
            timer.click(*position, 1, delay=0)
            time.sleep(1)
        if timer.image_exist(IMG.symbol_image[3], need_screen_shot=0):
            return literals.DOCK_FULL_FLAG
        if timer.image_exist(IMG.symbol_image[9], need_screen_shot=0, confidence=0.8):
            time.sleep(1)
            return literals.BATTLE_TIMES_EXCEED
        if time.time() - start_time > 15:
            if timer.process_bad_network():
                if timer.identify_page("fight_prepare_page"):
                    return start_march(timer, position)
                else:
                    NetworkErr("stats unknow")
            else:
                raise TimeoutError("map_fight prepare timeout")
    return literals.OPERATION_SUCCESS_FLAG


class FightResultInfo:
    def __init__(self, timer: Timer, ship_stats) -> None:
        try:
            mvp_pos = timer.wait_image(IMG.fight_image[14])
            self.mvp = get_nearest((mvp_pos[0], mvp_pos[1] + 20), BLOOD_BAR_POSITION[1])
        except Exception as e:
            timer.log_screen(name="mvp_image")
            timer.logger.warning(f"can't identify mvp, error: {e}")
        self.ship_stats = detect_ship_stats(timer, "sumup", ship_stats)

        self.result = timer.wait_images(IMG.fight_result, timeout=5)
        if timer.image_exist(IMG.fight_result["SS"], need_screen_shot=False):
            self.result = "SS"
        if self.result is None:
            timer.log_screen()
            timer.logger.warning("can't identify fight result, screen logged")

    def __str__(self):
        return f"MVP 为 {self.mvp} 号位, 战果为 {self.result}"

    def __lt__(self, other):  # <
        order = ["D", "C", "B", "A", "S", "SS"]
        if isinstance(other, FightResultInfo):
            other = other.result

        order.index(self.result) < order.index(other)

    def __le__(self, other):  # <=
        order = ["D", "C", "B", "A", "S", "SS"]
        if isinstance(other, FightResultInfo):
            other = other.result

        order.index(self.result) <= order.index(other)

    def __gt__(self, other):  # >
        return not (self <= other)

    def __ge__(self, other):  # >=
        return not (self < other)


class FightEvent:
    """战斗事件类
    事件列表: 战况选择, 获取资源, 索敌成功, 迂回, 阵型选择, 进入战斗, 是否夜战, 战斗结算, 获取舰船, 继续前进, 自动回港

    状态: 一个字典, 一共三种键值
        position: 位置, 所有事件均存在

        ship_stats: 我方舰船状态(仅在 "继续前进" 事件存在)

        enemys: 敌方舰船(仅在 "索敌成功" 事件存在), 字典或 "索敌失败"

        info: 其它额外信息(仅在 "自动回港" 事件存在)

    动作: 一个字符串
        "继续": 获取资源, 迂回, 战斗结算, 获取舰船, 自动回港等不需要决策的操作

        数字字符串: 战况选择的决策

        "SL"/数字字符串: 阵型选择的决策

        "继续"/ "SL": 进入战斗后的决策

        "战斗"/"撤退"/"迂回": 索敌成功的决策

        "追击"/"撤退": 夜战的决策

        "回港/前进": 是否前进的选择(战斗结算完毕后)

    结果: 一个字符串
        "无": 战况选择, 获取资源, 索敌成功, 阵型选择, 进入战斗, 是否夜战, 继续前进, 自动回港,

        (FightResultInfo): 表示战果信息, 战果结算

        舰船名: 获取舰船
    """

    def __init__(self, event, stats, action="继续", result="无"):
        self.event = event
        self.stats = stats
        self.action = action
        self.result = result

    def __str__(self) -> str:
        return f"事件:{self.event}, 状态:{self.stats}, 动作:{self.action}, 结果:{str(self.result)}"

    def __repr__(self) -> str:
        return f"FightEvent({self.event}, {self.stats}, {self.action}, {self.result})"


class FightHistory:
    """记录并处理战斗历史信息"""

    events = []

    def __init__(self) -> None:
        pass

    def add_event(self, event, point, action="继续", result="无"):
        self.events.append(FightEvent(event, point, action, result))

    def reset(self):
        self.events = []

    def get_fight_results(self):
        results_dict = {}
        results_list = []
        for event in self.events:
            if event.event == "战果结算":
                if event.stats["position"].isalpha():
                    results_dict[event.stats["position"]] = event.result
                else:
                    results_list.append(event.result)
        return results_list if len(results_list) else results_dict

    def get_last_point(self):
        return self.events[-1].stats["position"]

    def __str__(self) -> str:
        return "".join(str(event) + "\n" for event in self.events)


class FightInfo(ABC):
    """存储战斗中需要用到的所有状态信息, 以及更新逻辑"""

    def __init__(self, timer: Timer) -> None:
        self.timer = timer
        self.config = timer.config
        self.logger = timer.logger

        self.successor_states = (
            {}
        )  # 战斗流程的有向图建模，在不同动作有不同后继时才记录动作
        self.state2image = {}  # 所需用到的图片模板。格式为 [模板，等待时间]
        self.after_match_delay = {}  # 匹配成功后的延时。格式为 {状态名 : 延时时间(s),}
        self.last_state = ""
        self.last_action = ""
        self.state = ""
        self.enemys = {}  # 敌方舰船列表
        self.ship_stats = []  # 我方舰船血量列表
        self.oil = 10  # 我方剩余油量
        self.ammo = 10  # 我方剩余弹药量
        self.fight_history = FightHistory()  # 战斗结果记录

    def update_state(self):
        self.last_state = self.state

        # 计算当前可能的状态
        possible_states = copy.deepcopy(self.successor_states[self.last_state])
        if isinstance(possible_states, dict):
            possible_states = possible_states[self.last_action]
        modified_timeout = [-1 for _ in possible_states]  # 某些状态需要修改等待时间
        for i, state in enumerate(possible_states):
            if isinstance(state, list):
                state, timeout = state
                possible_states[i] = state
                modified_timeout[i] = timeout
        if self.config.SHOW_MATCH_FIGHT_STAGE:
            self.logger.debug("waiting:", possible_states, "  ")
        images = [self.state2image[state][0] for state in possible_states]
        timeout = [self.state2image[state][1] for state in possible_states]
        confidence = min(
            [0.8]
            + [
                self.state2image[state][2]
                for state in possible_states
                if len(self.state2image[state]) >= 3
            ]
        )
        timeout = [
            timeout[i] if modified_timeout[i] == -1 else modified_timeout[i]
            for i in range(len(timeout))
        ]
        timeout = max(timeout)
        # 等待其中一种出现
        fun_start_time = time.time()
        while time.time() - fun_start_time <= timeout:
            self._before_match()

            # 尝试匹配
            ret = [
                self.timer.image_exist(image, False, confidence=confidence)
                for image in images
            ]
            if any(ret):
                self.state = possible_states[ret.index(True)]
                # 查询是否有匹配后延时
                if self.state in self.after_match_delay:
                    delay = self.after_match_delay[self.state]
                    time.sleep(delay)

                if self.config.SHOW_MATCH_FIGHT_STAGE:
                    self.logger.info(f"matched: {self.state}")
                self._after_match()

                return self.state

        # 匹配不到时报错
        self.logger.warning(
            f"匹配状态失败! state: {self.state}  last_action: {self.last_action}"
        )
        self.timer.log_screen(True)
        for image in images:
            self.logger.log_image(image, f"match_{str(time.time())}.PNG")
        raise ImageNotFoundErr()

    def _before_match(self):
        """每一轮尝试匹配状态前执行的操作"""
        pass

    def _after_match(self):
        """匹配到状态后执行的操作"""
        if self.state == "spot_enemy_success":
            self.enemys = get_enemy_condition(self.timer, "fight")
        if self.state == "result":
            try:
                result = FightResultInfo(self.timer, self.ship_stats)
                self.ship_stats = result.ship_stats
                self.fight_history.add_event(
                    "战果结算",
                    {
                        "position": (
                            self.node
                            if "node" in self.__dict__
                            else f"此类战斗({type(self)})不支持节点信息"
                        )
                    },
                    result=result,
                )
            except Exception as e:
                self.logger.warning(f"战果结算记录失败：{e}")

    @abstractmethod
    def reset(self):
        """需要记录与初始化的战斗信息"""
        pass


class FightPlan(ABC):
    def __init__(self, timer: Timer):
        # 把 timer 引用作为内置对象，减少函数调用的时候所需传入的参数
        self.timer = timer
        self.config = timer.config
        self.logger = timer.logger
        self.fight_logs = []

    def fight(self):
        self.Info.reset()  # 初始化战斗信息
        while True:
            ret = self._make_decision()
            if ret == literals.FIGHT_CONTINUE_FLAG:
                continue
            elif ret == "need SL":
                self._SL()
                return "SL"
            elif ret == literals.FIGHT_END_FLAG:
                self.timer.set_page(self.Info.end_page)
                self.fight_logs.append(self.Info.fight_history)
                return "success"

    def run_for_times(self, times, gap=1800):
        """多次执行同一任务, 自动进行远征操作
        Args:
            times (int): 任务执行总次数

            gap (int): 强制远征检查的间隔时间
        Raise:
            RuntimeError: 战斗进行时出现错误
        Returns:
            str:
                "OK": 任务正常结束

                "dock is full" 因为船坞已满并且没有设置解装因此退出任务
        """
        assert times >= 1
        expedition = Expedition(self.timer)
        last_flag = self.run() != "SL"
        self.ii = 1
        for _ in range(1, times):
            self.timer.logger.info(f"已出击次数:{_}，目标次数{times}")
            if time.time() - self.timer.last_expedition_check_time >= gap:
                expedition.run(True)
                last_flag = False
            elif (
                isinstance(self.timer.now_page, Node)
                and self.timer.now_page.name == "map_page"
            ):
                expedition.run(False)
                self.timer.goto_game_page("map_page")

            fight_flag = self.run()
            self.ii += 1
            fight_flag != "SL"

            if fight_flag not in ["SL", "success"]:
                if fight_flag == "dock is full":
                    return "dock is full"
                raise RuntimeError(f"战斗进行时出现异常, 信息为 {fight_flag}")
        return "OK"

    def run(self):
        """主函数，负责一次完整的战斗.
        Returns:
            str:
                'dock is full': 船坞已满并且没有设置自动解装

                'fight end': 战斗结束标志, 一般不返回这个, 和 success 相同

                'out of times': 战斗超时

                'SL': 进行了 SL 操作

                'success': 战斗流程正常结束(到达了某个结束点或者选择了回港)

        """
        # 战斗前逻辑
        ret = self._enter_fight()

        if ret == literals.OPERATION_SUCCESS_FLAG:
            pass
        elif ret == literals.DOCK_FULL_FLAG:
            # 自动解装功能
            if self.config.dock_full_destroy:
                self.timer.relative_click(0.38, 0.565)
                DestroyShip(self.timer)
                return self.run()
            else:
                return ret
        elif ret == literals.FIGHT_END_FLAG:
            self.timer.set_page(self.Info.end_page)
            return ret
        elif ret == literals.BATTLE_TIMES_EXCEED:
            return ret
        else:
            self.logger.error("无法进入战斗, 原因未知! 屏幕状态已记录")
            self.timer.log_screen()
            raise BaseException(str(time.time()) + "enter fight error")

        # 战斗中逻辑
        return self.fight()

    def run_for_times_condition(self, times, last_point, result="S", insist_time=900):
        """有战果要求的多次运行, 使用前务必检查参数是否有误, 防止死循环

        Args:
            times: 次数

            last_point: 最后一个点

            result: 战果要求

            insist_time: 如果大于这个时间工作量未减少则退出工作

        Returns:
            str:
                "OK": 任务顺利结束

                "dock is full": 因为船坞已满并且不允许解装所以停止
        """
        if not isinstance(result, str) or not isinstance(last_point, str):
            raise TypeError(
                f"last_point, result must be str,but is {type(last_point)}, {type(result)}"
            )
        if result not in ["S", "A", "B", "C", "D", "SS"]:
            raise ValueError(
                f"result value {result} is illegal, it should be 'A','B','C','D','S' or 'SS'"
            )
        if (
            len(last_point) != 1
            or ord(last_point) > ord("Z")
            or ord(last_point) < ord("A")
        ):
            raise ValueError("last_point should be a uppercase within 'A' to 'Z'")
        import time

        result_list = ["SS", "S", "A", "B", "C", "D"]
        start_time, run = time.time(), False
        while times:
            ret = self.run()
            last_flag = ret != "SL"
            if ret == "dock is full":
                self.timer.logger.error("船坞已满, 无法继续")
                return ret

            self.logger.info("战斗信息:\n" + str(self.Info.fight_history))
            fight_results = sorted(self.Info.fight_history.get_fight_results().items())
            # 根据情况截取战果，并在result_list查找索引
            if len(fight_results):
                if str(fight_results[-1][1])[-2].isalpha():
                    fight_result_index = result_list.index(
                        str(fight_results[-1][1])[-2:]
                    )
                else:
                    fight_result_index = result_list.index(
                        str(fight_results[-1][1])[-1]
                    )

            finish = (
                len(fight_results)
                and fight_results[-1][0] == last_point
                and fight_result_index <= result_list.index(result)
            )
            if not finish:
                self.timer.logger.info(
                    f"不满足预设条件, 此次战斗不计入次数, 剩余战斗次数:{times}"
                )
                if time.time() - start_time > insist_time:
                    return False
            else:
                start_time, times = time.time(), times - 1
                self.timer.logger.info(
                    f"完成了一次满足预设条件的战斗, 剩余战斗次数:{times}"
                )
        return "OK"

    def update_state(self, *args, **kwargs):
        try:
            self.Info.update_state()
            state = self.Info.state
            self.timer.keep_try_update_fight = 0
        except ImageNotFoundErr as _:
            # 处理点击延迟或者网络波动导致的匹配失败
            if (
                hasattr(self.timer, "keep_try_update_fight")
                and self.timer.keep_try_update_fight > 3
            ):
                return "need_SL"
            elif hasattr(self.timer, "keep_try_update_fight"):
                self.timer.keep_try_update_fight += 1
            else:
                self.timer.keep_try_update_fight = 1
            self.logger.warning("Image Match Failed, Trying to Process")
            if self.timer.is_other_device_login():
                self.timer.process_other_device_login()  # TODO: 处理其他设备登录
            if self.timer.is_bad_network(timeout=5):
                self.timer.process_bad_network(extra_info="update_state", timeout=5)
            self._make_decision(skip_update=True)
            # if self.Info.last_state == "spot_enemy_success":
            #     if self.timer.image_exist(IMG.fight_image[2]):
            #         self.timer.click(900, 500)
            # if self.Info.last_state in ["proceed", "night"] and self.timer.image_exist(
            #     IMG.fight_image[5:7]
            # ):
            #     if self.Info.last_action == "yes":
            #         self.timer.click(325, 350, times=1)
            #     else:
            #         self.timer.click(615, 350, times=1)

            if "try_times" not in kwargs.keys():
                return self.update_state(try_times=1)
            else:
                time.sleep(10 * 2.5 ** kwargs["try_times"])
                return self.update_state(try_times=kwargs["try_times"] + 1)
        return state

    @abstractmethod
    def _enter_fight(self) -> str:
        pass

    @abstractmethod
    def _make_decision(self, *args, **kwargs) -> str:
        pass

    # =============== 战斗中通用的操作 ===============
    def _SL(self):
        self.timer.logger.debug("正在执行SL操作")
        # 重置地图节点信息
        self.timer.reset_chapter_map()

        self.timer.restart()
        self.timer.go_main_page()
        self.timer.set_page("main_page")


class DecisionBlock:
    """地图上一个节点的决策模块"""

    def __init__(self, timer: Timer, args):
        self.timer = timer
        self.config = timer.config
        self.logger = timer.logger

        self.__dict__.update(args)

        # 用于根据规则设置阵型
        self.set_formation_by_rule = False
        self.formation_by_rule = 0

    def _check_rules(self, enemys: dict):
        for rule in self.enemy_rules:
            condition, act = rule
            rcondition = ""
            last = 0
            for i, ch in enumerate(condition):
                if ord(ch) > ord("Z") or ord(ch) < ord("A"):
                    if last != i:
                        if condition[last:i] in ALL_SHIP_TYPES:
                            rcondition += f"enemys.get('{condition[last:i]}', 0)"
                        else:
                            rcondition += condition[last:i]
                    rcondition += ch
                    last = i + 1

            if self.config.SHOW_ENEMY_RULES:
                self.logger.info(rcondition)
            if eval(rcondition):
                return act

    def make_decision(self, state, last_state, last_action, Info: FightInfo):
        # sourcery skip: extract-method
        """单个节点的决策"""
        enemys = Info.enemys
        if state in ["fight_period", "night_fight_period"]:
            if self.SL_when_enter_fight == True:
                Info.fight_history.add_event(
                    "进入战斗",
                    {
                        "position": (
                            Info.node
                            if "node" in Info.__dict__
                            else f"此类战斗({type(Info)})不包含节点信息"
                        )
                    },
                    "SL",
                )
                return None, "need SL"
            return None, literals.FIGHT_CONTINUE_FLAG

        elif state == "spot_enemy_success":
            retreat = (
                self.supply_ship_mode == 1 and enemys.get(SAP, 0) == 0
            )  # 功能: 遇到补给舰则战斗，否则撤退
            can_detour = self.timer.image_exist(
                IMG.fight_image[13]
            )  # 判断该点是否可以迂回
            detour = can_detour and self.detour  # 由 Node 指定是否要迂回

            # 功能, 根据敌方阵容进行选择
            act = self._check_rules(enemys=enemys)

            if act == "retreat":
                retreat = True
            elif act == "detour":
                try:
                    assert can_detour, "该点无法迂回, 但是规则中指定了迂回"
                except AssertionError:
                    raise ValueError("该点无法迂回, 但在规则中指定了迂回")
                detour = True
            elif isinstance(act, int):
                self.set_formation_by_rule = True
                self.formation_by_rule = act

            if retreat:
                self.timer.click(677, 492, delay=0.2)
                Info.fight_history.add_event(
                    "索敌成功",
                    {
                        "position": (
                            Info.node
                            if "node" in Info.__dict__
                            else f"此类战斗({type(Info)})不包含节点信息"
                        )
                    },
                    "撤退",
                )
                return "retreat", literals.FIGHT_END_FLAG
            elif detour:
                image_detour = IMG.fight_image[13]
                if self.timer.click_image(image=image_detour, timeout=2.5):
                    self.timer.logger.info("成功执行迂回操作")
                else:
                    self.timer.logger.error("未找到迂回按钮")
                    self.timer.log_screen(True)
                    raise ImageNotFoundErr("can't found image")

                # self.timer.click(540, 500, delay=0.2)
                Info.fight_history.add_event(
                    "索敌成功",
                    {
                        "position": (
                            Info.node
                            if "node" in Info.__dict__
                            else f"此类战斗({type(Info)})不包含节点信息"
                        )
                    },
                    "迂回",
                )
                return "detour", literals.FIGHT_CONTINUE_FLAG

            Info.fight_history.add_event(
                "索敌成功",
                {
                    "position": (
                        Info.node
                        if "node" in Info.__dict__
                        else f"此类战斗({type(Info)})不包含节点信息"
                    )
                },
                "战斗",
            )
            if self.long_missile_support == True:
                image_missile_support = IMG.fight_image[17]
                if self.timer.click_image(image=image_missile_support, timeout=2.5):
                    self.timer.logger.info("成功开启远程导弹支援")
                else:
                    self.timer.logger.error("未找到远程支援按钮")
                    raise ImageNotFoundErr("can't found image of long_missile_support")
            self.timer.click(855, 501, delay=0.2)
            # self.timer.click(380, 520, times=2, delay=0.2) # TODO: 跳过可能的开幕支援动画，实现有问题
            return "fight", literals.FIGHT_CONTINUE_FLAG
        elif state == "formation":
            spot_enemy = last_state == "spot_enemy_success"
            value = self.formation
            if spot_enemy:
                if self.SL_when_detour_fails and last_action == "detour":
                    Info.fight_history.add_event(
                        "迂回",
                        {
                            "position": (
                                Info.node
                                if "node" in Info.__dict__
                                else f"此类战斗({type(Info)})不包含节点信息"
                            )
                        },
                        result="失败",
                    )
                    Info.fight_history.add_event(
                        "阵型选择",
                        {
                            "enemys": enemys,
                            "position": (
                                Info.node
                                if "node" in Info.__dict__
                                else f"此类战斗({type(Info)})不包含节点信息"
                            ),
                        },
                        action="SL",
                    )
                    return None, "need SL"

                if self.set_formation_by_rule:
                    self.logger.debug("set formation by rule:", self.formation_by_rule)
                    value = self.formation_by_rule
                    self.set_formation_by_rule = False
            else:
                if self.SL_when_spot_enemy_fails:
                    Info.fight_history.add_event(
                        "阵型选择",
                        {
                            "enemys": "索敌失败",
                            "position": (
                                Info.node
                                if "node" in Info.__dict__
                                else f"此类战斗({type(Info)})不包含节点信息"
                            ),
                        },
                        action="SL",
                    )
                    return None, "need SL"
                if self.formation_when_spot_enemy_fails != False:
                    value = self.formation_when_spot_enemy_fails
            Info.fight_history.add_event(
                "阵型选择",
                {
                    "enemys": (
                        enemys if last_state == "spot_enemy_success" else "索敌失败"
                    ),
                    "position": (
                        Info.node
                        if "node" in Info.__dict__
                        else f"此类战斗({type(Info)})不包含节点信息"
                    ),
                },
                action=value,
            )
            # import random
            # if random.random() > 0.5:
            #     print("这次没点起")
            # else:
            #     self.timer.click(573, value * 100 - 20, delay=2)
            self.timer.click(573, value * 100 - 20, delay=2)
            return value, literals.FIGHT_CONTINUE_FLAG
        elif state == "night":
            is_night = self.night
            Info.fight_history.add_event(
                "是否夜战",
                {
                    "position": (
                        Info.node
                        if "node" in Info.__dict__
                        else f"此类战斗({type(Info)})不包含节点信息"
                    )
                },
                action="追击" if is_night else "撤退",
            )

            match_night(self.timer, is_night)
            if is_night:
                # self.timer.click(325, 350)
                return "yes", literals.FIGHT_CONTINUE_FLAG
            else:
                # self.timer.click(615, 350)
                return "no", literals.FIGHT_CONTINUE_FLAG

        elif state == "result":
            # time.sleep(1.5)
            # self.timer.click(900, 500, times=2, delay=0.2)
            click_result(self.timer)
            return None, literals.FIGHT_CONTINUE_FLAG
        elif state == "get_ship":
            get_ship(self.timer)
            return None, literals.FIGHT_CONTINUE_FLAG
        else:
            self.logger.error("Unknown State")
            raise BaseException()


class IndependentFightPlan(FightPlan):
    def __init__(
        self,
        timer: Timer,
        end_image,
        plan_path=None,
        default_path="plans/default.yaml",
        *args,
        **kwargs,
    ):
        """创建一个独立战斗模块, 处理从形如战役点击出征到收获舰船(或战果结算)的整个过程
        Args:
            end_image (MyTemplate): 整个战斗流程结束后的图片
        """
        super().__init__(timer)
        default_args = yaml_to_dict(default_path)
        node_defaults = default_args["node_defaults"]
        node_args = yaml_to_dict(plan_path) if (plan_path is not None) else kwargs
        node_args = recursive_dict_update(node_defaults, node_args)
        self.decision_block = DecisionBlock(timer, node_args)
        self.Info = IndependentFightInfo(timer, end_image)

    def run(self):
        super().fight()

    def _make_decision(self, *args, **kwargs):
        if "skip_update" not in kwargs.keys():
            state = self.update_state()
        if self.Info.state == "battle_page":
            return literals.FIGHT_END_FLAG
        if state == "need SL":
            return "need SL"

        # 进行通用NodeLevel决策
        action, fight_stage = self.decision_block.make_decision(
            self.Info.state, self.Info.last_state, self.Info.last_action, self.Info
        )
        self.Info.last_action = action
        return fight_stage


class IndependentFightInfo(FightInfo):
    def __init__(self, timer: Timer, end_image) -> None:
        super().__init__(timer)

        self.end_page = "battle_page"

        self.successor_states = {
            "proceed": ["spot_enemy_success", "formation", "fight_period"],
            "spot_enemy_success": {
                "retreat": ["battle_page"],
                "fight": ["formation", "fight_period"],
            },
            "formation": ["fight_period"],
            "fight_period": ["night", "result"],
            "night": {
                "yes": ["night_fight_period"],
                "no": [["result", 8]],
            },
            "night_fight_period": ["result"],
            "result": ["battle_page"],  # 两页战果
        }

        self.state2image = {
            "proceed": [IMG.fight_image[5], 5],
            "spot_enemy_success": [IMG.fight_image[2], 15],
            "formation": [IMG.fight_image[1], 15],
            "fight_period": [IMG.symbol_image[4], 3],
            "night": [IMG.fight_image[6], 120],
            "night_fight_period": [IMG.symbol_image[4], 3],
            "result": [IMG.fight_image[16], 60],
            "battle_page": [end_image, 5],
        }

    def reset(self):
        self.last_state = ""
        self.last_action = ""
        self.state = "proceed"

    def _before_match(self):
        # 点击加速
        if self.state in ["proceed"]:
            p = self.timer.click(
                380, 520, delay=0, enable_subprocess=True, not_show=True
            )
        self.timer.update_screen()

    def _after_match(self):
        pass  # 战役的敌方信息固定，不用获取

"""
常规战决策模块/地图战斗用模板
"""

MAP_NUM = [5, 6, 4, 4, 5, 4, 5, 5, 4]  # 每一章的地图数量


class NormalFightInfo(FightInfo):
    # ==================== Unified Interface ====================
    def __init__(self, timer: Timer, chapter_id, map_id) -> None:
        super().__init__(timer)

        self.point_positions = None
        self.end_page = "map_page"
        self.map_image = IMG.identify_images.map_page
        self.ship_image = [IMG.symbol_image[8]] + [IMG.symbol_image[13]]
        self.chapter = chapter_id  # 章节名,战役为 'battle', 演习为 'exercise'
        self.map = map_id  # 节点名
        self.ship_position = (0, 0)
        self.node = "A"  # 常规地图战斗中,当前战斗点位的编号
        self.successor_states = {
            "proceed": {
                "yes": [
                    "fight_condition",
                    "spot_enemy_success",
                    "formation",
                    "fight_period",
                    "map_page",
                ],
                "no": ["map_page"],
            },
            "fight_condition": ["spot_enemy_success", "formation", "fight_period"],
            "spot_enemy_success": {
                "detour": [
                    "fight_condition",
                    "spot_enemy_success",
                    "formation",
                    "fight_period",
                ],
                "retreat": ["map_page"],
                "fight": ["formation", "fight_period"],
            },
            "formation": ["fight_period"],
            "fight_period": ["night", "result"],
            "night": {
                "yes": ["result"],
                "no": [["result", 10]],
            },
            "result": [
                "proceed",
                "map_page",
                "get_ship",
                "flagship_severe_damage",
            ],  # 两页战果
            "get_ship": ["proceed", "map_page", "flagship_severe_damage"],  # 捞到舰船
            "flagship_severe_damage": ["map_page"],
        }

        self.state2image = {
            "proceed": [IMG.fight_image[5], 7.5],
            "fight_condition": [IMG.fight_image[10], 22.5],
            "spot_enemy_success": [IMG.fight_image[2], 22.5],
            "formation": [IMG.fight_image[1], 22.5],
            "fight_period": [IMG.symbol_image[4], 30],
            "night": [IMG.fight_image[6], 150],
            "result": [IMG.fight_image[3], 90],
            "get_ship": [self.ship_image, 5],
            "flagship_severe_damage": [IMG.fight_image[4], 7.5],
            "map_page": [self.map_image, 7.5],
        }

        self.after_match_delay = {
            "night": 1.75,
            "proceed": 0.5,
            "get_ship": 1,
        }

    def reset(self):
        self.fight_history.reset()
        self.last_state = "proceed"
        self.last_action = "yes"
        self.state = "proceed"  # 初始状态等同于 proceed 选择 yes

    def _before_match(self):
        # 点击加速
        if (
            self.last_state in ["proceed", "fight_condition"]
            or self.last_action == "detour"
        ):
            self.timer.click(250, 520, delay=0, enable_subprocess=True)

        self.timer.update_screen()

        # 在地图上走的过程中获取舰船位置
        if self.last_state == "proceed" or self.last_action == "detour":
            self._update_ship_position()
            self._update_ship_point()
            pos = self.timer.get_image_position(IMG.confirm_image[3], False, 0.8)
            if pos:
                self.timer.ConfirmOperation(delay=0.25, must_confirm=1, confidence=0.8)

    def _after_match(self):
        # 在某些State下可以记录额外信息
        if self.state == "spot_enemy_success":
            get_enemy_condition(self.timer, "fight")
        super()._after_match()

    # ======================== Functions ========================

    def _update_ship_position(self):
        """在战斗移动界面(有一个黄色小船在地图上跑)更新黄色小船的位置"""
        pos = self.timer.get_image_position(IMG.fight_image[7], False, 0.8)
        if pos is None:
            pos = self.timer.get_image_position(IMG.fight_image[8], False, 0.8)
        if pos is None:
            return
        self.ship_position = pos
        if self.config.SHOW_MAP_NODE:
            self.timer.logger.debug(self.ship_position)

    def _update_ship_point(self):
        """更新黄色小船(战斗地图上那个)所在的点位 (1-1A 这种,'A' 就是点位)"""

        self.node = "A"
        for i in range(26):
            ch = chr(ord("A") + i)
            if ch not in self.point_positions.keys():
                continue
            if CalcDis(self.point_positions[ch], self.ship_position) < CalcDis(
                self.point_positions[self.node], self.ship_position
            ):
                self.node = ch

        if self.config.SHOW_MAP_NODE:
            self.timer.logger.debug(self.node)

    def load_point_positions(self, map_path):
        """地图文件命名格式: [chapter]-[map].yaml"""
        self.point_positions = yaml_to_dict(
            os.path.join(map_path, str(self.chapter) + "-" + str(self.map) + ".yaml")
        )


def check_blood(blood, rule) -> bool:
    """检查血量状态是否满足前进条件
        >>>check_blood([None, 1, 1, 1, 2, -1, -1], [2, 2, 2, -1, -1, -1])

        >>>True
    Args:
        blood (list): 1-based
        rule (list): 0-based
    """
    l = max(len(blood) - 1, len(rule))
    for i in range(l):
        if blood[i + 1] == -1 or rule[i] == -1:
            continue
        if blood[i + 1] >= rule[i]:
            return False
    return True


class NormalFightPlan(FightPlan):
    """ " 常规战斗的决策模块"""

    """ 多点战斗基本模板 """

    def __init__(self, timer: Timer, plan_path, fleet_id=None, fleet=-1) -> None:
        """初始化决策模块,可以重新指定默认参数,优先级更高

        Args:
            fleet_id: 指定舰队编号, 如果为 None 则使用计划中的参数

            plan_path: 绝对路径 / 以 PLAN_ROOT 为根的相对路径

            fleet: 舰队成员, ["", "1号位", "2号位", ...], 如果为 None 则全部不变, 为 "" 则该位置无舰船, 为 -1 则不覆盖 yaml 文件中的参数

        Raises:
            BaseException: _description_
        """

        super().__init__(timer)

        # 从配置文件加载计划
        default_args = yaml_to_dict(os.path.join(self.config.PLAN_ROOT, "default.yaml"))
        if os.path.isabs(plan_path):
            plan_args = yaml_to_dict(plan_path)
        else:
            plan_args = yaml_to_dict(os.path.join(self.config.PLAN_ROOT, plan_path))

        # 从参数加载计划
        if fleet_id is not None:
            plan_args["fleet_id"] = fleet_id  # 舰队编号
        if fleet != -1:
            plan_args["fleet"] = fleet

        # 检查参数完整情况
        if "fleet_id" not in plan_args:
            self.logger.warning(
                f"未指定作战舰队, 默认采用第 {default_args['normal_fight_defaults']['fleet_id']} 舰队作战"
            )

        # 从默认参数加载
        plan_defaults = default_args["normal_fight_defaults"]
        plan_defaults.update({"node_defaults": default_args["node_defaults"]})
        args = recursive_dict_update(plan_defaults, plan_args, skip=["node_args"])
        self.__dict__.update(args)

        # 加载节点配置
        self.nodes = {}
        for node_name in self.selected_nodes:
            node_args = copy.deepcopy(self.node_defaults)
            if (
                "node_args" in plan_args
                and plan_args["node_args"] is not None
                and node_name in plan_args["node_args"]
            ):
                node_args = recursive_dict_update(
                    node_args, plan_args["node_args"][node_name]
                )
            self.nodes[node_name] = DecisionBlock(timer, node_args)
        self._load_fight_info()

    def _load_fight_info(self):
        # 信息记录器
        self.Info = NormalFightInfo(self.timer, self.chapter, self.map)
        self.Info.load_point_positions(os.path.join(MAP_ROOT, "normal"))

    def _go_map_page(self):
        """活动多点战斗必须重写该模块"""
        """ 进入选择战斗地图的页面 """
        """ 这个模块负责的工作在战斗结束后如果需要进行重复战斗, 则不会进行 """
        self.timer.goto_game_page("map_page")

    def _go_fight_prepare_page(self) -> None:
        """活动多点战斗必须重写该模块"""
        """(从当前战斗结束后跳转到的页面)进入准备战斗的页面"""
        if not self.timer.ui.is_normal_fight_prepare:
            self.timer.goto_game_page("map_page")
        self.timer.goto_game_page("fight_prepare_page")
        self.timer.ui.is_normal_fight_prepare = True

    def _enter_fight(self, *args, **kwargs):
        """
        从任意界面进入战斗.

        :return: 进入战斗状态信息，包括['success', 'dock is full'].
        """
        if self.chapter != self.timer.port.chapter or self.map != self.timer.port.map:
            self._go_map_page()
            self._change_fight_map(self.chapter, self.map)
            self.timer.port.chapter = self.chapter
            self.timer.port.map = self.map
        # if not hasattr(self, "level_checked"):
        self.timer.wait_images(
            [self.Info.map_image] + [IMG.identify_images["fight_prepare_page"]],
            timeout=3,
        )
        self._go_fight_prepare_page()

        #custom code region BEGIN
        self.timer.logger.info(f"ii = {self.ii}, ii % 4 == {self.ii % 4}")
        if self.ii % 4 == 0:
            self.timer.logger.info(f"auto supply: on")
            SetAutoSupply(self.timer, type = 1)
        elif self.ii % 4 == 1:
            self.timer.logger.info(f"auto supply: off")
            SetAutoSupply(self.timer, type = 0)
        #custom code region END

        MoveTeam(self.timer, self.fleet_id)
        if (
            self.fleet is not None
            and self.timer.port.fleet[self.fleet_id] != self.fleet
        ):
            ChangeShips(self.timer, self.fleet_id, self.fleet)
            self.timer.port.fleet[self.fleet_id] = self.fleet[:]

        self.Info.ship_stats = detect_ship_stats(self.timer)
        quick_repair(self.timer, self.repair_mode, self.Info.ship_stats)

        # TODO: 这里应该只catch network error，太宽的catch会导致其他错误被隐藏
        # except AssertionError:
        #     if "process_err" in kwargs and kwargs["process_err"] == False:
        #         raise ImageNotFoundErr("进入战斗前置界面错误")
        #     self.logger.warning("进入战斗前置界面不正确")
        #     self.timer.process_bad_network()
        #     return self._enter_fight(process_err=False)

        return start_march(self.timer)

    def _make_decision(
        self, *args, **kwargs
    ):  # sourcery skip: extract-duplicate-method
        if "skip_update" not in kwargs.keys():
            state = self.update_state()
        else:
            state = self.Info.state
        if state == "need SL":
            return "need SL"

        # 进行 MapLevel 的决策
        if state == "map_page":
            self.Info.fight_history.add_event(
                "自动回港", {"position": self.Info.node, "info": "正常"}
            )
            return literals.FIGHT_END_FLAG

        elif state == "fight_condition":
            value = self.fight_condition
            self.timer.click(*FIGHT_CONDITIONS_POSITION[value])
            self.Info.last_action = value
            self.Info.fight_history.add_event(
                "战况选择", {"position": self.Info.node}, value
            )
            # self.fight_recorder.append(StageRecorder(self.Info, self.timer))
            return literals.FIGHT_CONTINUE_FLAG

        # 不在白名单之内 SL
        if self.Info.node not in self.selected_nodes:
            # 可以撤退点撤退
            if state == "spot_enemy_success":
                self.timer.click(677, 492, delay=0)
                self.Info.last_action = "retreat"
                self.Info.fight_history.add_event(
                    "索敌成功",
                    {"position": self.Info.node, "enemys": "不在预设点, 不进行索敌"},
                    "撤退",
                )
                return literals.FIGHT_END_FLAG
            # 不能撤退退游戏
            elif state == "formation":
                self.Info.fight_history.add_event(
                    "阵型选择", {"position": self.Info.node}, "SL"
                )
                return "need SL"
            elif state == "fight_period":
                self.Info.fight_history.add_event(
                    "进入战斗", {"position": self.Info.node}, "SL"
                )
                return "need SL"

        elif state == "proceed":
            is_proceed = self.nodes[self.Info.node].proceed and check_blood(
                self.Info.ship_stats, self.nodes[self.Info.node].proceed_stop
            )

            if is_proceed:
                self.timer.click(325, 350)
                self.Info.last_action = "yes"
                self.Info.fight_history.add_event(
                    "继续前进",
                    {"position": self.Info.node, "ship_stats": self.Info.ship_stats},
                    "前进",
                )
                return literals.FIGHT_CONTINUE_FLAG
            else:
                self.timer.click(615, 350)
                self.Info.last_action = "no"
                self.Info.fight_history.add_event(
                    "继续前进",
                    {"position": self.Info.node, "ship_stats": self.Info.ship_stats},
                    "回港",
                )
                return literals.FIGHT_END_FLAG

        elif state == "flagship_severe_damage":
            self.timer.click_image(IMG.fight_image[4], must_click=True, delay=0.25)
            self.Info.fight_history.add_event(
                "自动回港", {"position": self.Info.node, "info": "旗舰大破"}
            )
            return "fight end"

        # Todo:燃油耗尽自动回港

        # 进行通用 NodeLevel 决策
        action, fight_stage = self.nodes[self.Info.node].make_decision(
            state, self.Info.last_state, self.Info.last_action, self.Info
        )
        self.Info.last_action = action
        # self.fight_recorder.append(StageRecorder(self.Info, self.timer))

        return fight_stage

    # ======================== Functions ========================
    def _get_chapter(self) -> int:
        """在出征界面获取当前章节(远征界面也可获取)

        Raises:
            TimeoutError: 无法获取当前章节

        Returns:
            int: 当前章节
        """
        for try_times in range(5):
            time.sleep(0.15 * 2**try_times)
            self.timer.update_screen()
            for i in range(1, len(IMG.chapter_image)):
                if self.timer.image_exist(IMG.chapter_image[i], 0):
                    return i

        raise TimeoutError("can't verify chapter")

    def _move_chapter(self, target_chapter, now_chapter=None):
        """移动地图章节到 target_chapter
        含错误检查

        Args:
            target_chapter (int): 目标
            now_chapter (_type_, optional): 现在的章节. Defaults to None.
        Raise:
            ImageNotFoundErr:如果没有找到章节标志或地图界面标志
        """
        if not self.timer.identify_page("map_page"):
            raise ImageNotFoundErr("not on page 'map_page' now")

        if now_chapter == target_chapter:
            return
        try:
            if now_chapter is None:
                now_chapter = self._get_chapter()
            if self.config.SHOW_CHAPTER_INFO:
                self.timer.logger.debug("NowChapter:", now_chapter)
            if now_chapter > target_chapter:
                if now_chapter - target_chapter >= 3:
                    now_chapter -= 3
                    self.timer.click(95, 97, delay=0)

                elif now_chapter - target_chapter == 2:
                    now_chapter -= 2
                    self.timer.click(95, 170, delay=0)

                elif now_chapter - target_chapter == 1:
                    now_chapter -= 1
                    self.timer.click(95, 229, delay=0)

            else:
                if now_chapter - target_chapter <= -3:
                    now_chapter += 3
                    self.timer.click(95, 485, delay=0)

                elif now_chapter - target_chapter == -2:
                    now_chapter += 2
                    self.timer.click(95, 416, delay=0)

                elif now_chapter - target_chapter == -1:
                    now_chapter += 1
                    self.timer.click(95, 366, delay=0)

            if not self.timer.wait_image(IMG.chapter_image[now_chapter]):
                raise ImageNotFoundErr(
                    "after 'move chapter' operation but the chapter do not move"
                )

            time.sleep(0.15)
            self._move_chapter(target_chapter, now_chapter)
        except:

            self.logger.warning(
                f"切换章节失败 target_chapter: {target_chapter}   now: {now_chapter}"
            )
            if self.timer.process_bad_network("move_chapter"):
                self._move_chapter(target_chapter)
            else:
                raise ImageNotFoundErr("unknow reason can't find chapter image")

    def _verify_map(self, target_map, chapter, need_screen_shot=True, timeout=0):
        if timeout == 0:
            return self.timer.image_exist(
                IMG.normal_map_image[f"{str(chapter)}-"][target_map - 1],
                need_screen_shot,
                confidence=0.85,
            )
        return self.timer.wait_image(
            IMG.normal_map_image[f"{str(chapter)}-"][target_map - 1],
            confidence=0.85,
            timeout=timeout,
            gap=0.03,
        )

    def _get_map(self, chapter, need_screen_shot=True) -> int:
        """出征界面获取当前显示地图节点编号
        例如在出征界面显示的地图 2-5,则返回 5

        Returns:
            int: 节点编号
        """
        for try_times in range(5):
            time.sleep(0.15 * 2**try_times)
            if need_screen_shot:
                self.timer.update_screen()

            # 通过+-1来匹配0，1开始的序号
            for map in range(1, MAP_NUM[chapter - 1] + 1):
                if self._verify_map(map, chapter, need_screen_shot=False):
                    return map

        raise TimeoutError("can't verify map")

    def _move_map(self, target_map, chapter):
        """改变地图节点,不检查是否有该节点
        含网络错误检查
        Args:
            target_map (_type_): 目标节点

        """
        if not self.timer.identify_page("map_page"):
            raise ImageNotFoundErr("not on page 'map_page' now")

        now_map = self._get_map(chapter)
        try:
            if self.config.SHOW_CHAPTER_INFO:
                self.timer.logger.debug("now_map:", now_map)
            if target_map > now_map:
                for i in range(target_map - now_map):
                    self.timer.swipe(715, 147, 552, 147, duration=0.25)
                    if not self._verify_map(now_map + (i + 1), chapter, timeout=4):
                        raise ImageNotFoundErr(
                            "after 'move map' operation but the chapter do not move"
                        )
                    time.sleep(0.15)
            else:
                for i in range(now_map - target_map):
                    self.timer.swipe(552, 147, 715, 147, duration=0.25)
                    if not self._verify_map(now_map - (i + 1), chapter, timeout=4):
                        raise ImageNotFoundErr(
                            "after 'move map' operation but the chapter do not move"
                        )
                    time.sleep(0.15)
        except:
            self.logger.error(f"切换地图失败 target_map: {target_map}   now: {now_map}")
            if self.timer.process_bad_network():
                self._move_map(target_map, chapter)
            else:
                raise ImageNotFoundErr(
                    "unknown reason can't find number image" + str(target_map)
                )

    def _change_fight_map(self, chapter, map):
        """活动多点战斗必须重写该模块"""
        """ 这个模块负责的工作在战斗结束后如果需要进行重复战斗, 则不会进行 """
        """在地图界面改变战斗地图(通常是为了出征)
        可以处理网络错误
        Args:
            chapter (int): 目标章节
            map (int): 目标节点

        Raises:
            ValueError: 不在地图界面
            ValueError: 不存在的节点
        """
        if self.timer.now_page.name != "map_page":
            raise ValueError(
                "can't change fight map at page:", self.timer.now_page.name
            )
        if map - 1 not in range(MAP_NUM[chapter - 1]):
            raise ValueError(
                f"map {str(map)} not in the list of chapter {str(chapter)}"
            )

        self._move_chapter(chapter)
        self._move_map(map, chapter)
        self.Info.chapter = self.chapter
        self.Info.map = self.map

class EventFightPlan20240930(Event, NormalFightPlan):
    def __init__(
        self,
        timer: Timer,
        plan_path,
        fleet_id=None,
        event="20240930",
    ):
        """
        Args:
            fleet_id : 新的舰队参数, 优先级高于 plan 文件, 如果为 None 则使用计划参数.

        """
        self.event_name = event
        self.ii = 0
        NormalFightPlan.__init__(self, timer, plan_path, fleet_id=fleet_id)
        Event.__init__(self, timer, event)

    def _load_fight_info(self):
        self.Info = EventFightInfo20240930(self.timer, self.chapter, self.map)
        self.Info.load_point_positions(os.path.join(MAP_ROOT, "event", self.event_name))

    def _change_fight_map(self, chapter_id, map_id):
        """选择并进入战斗地图(chapter-map)"""
        self.change_difficulty(chapter_id)

    def _go_fight_prepare_page(self) -> None:
        # 进入相应地图页面
        if not self.timer.image_exist(self.Info.event_image[1]):
            self.timer.relative_click(*NODE_POSITION[self.map])

        if not self.timer.click_image(self.event_image[1], timeout=10):
            self.timer.logger.warning("进入战斗准备页面失败,重新尝试进入战斗准备页面")
            self.timer.relative_click(*NODE_POSITION[self.map])
            self.timer.click_image(self.event_image[1], timeout=10)

        try:
            self.timer.wait_pages("fight_prepare_page", after_wait=0.15)
        except Exception as e:
            self.timer.logger.warning(
                f"匹配fight_prepare_page失败，尝试重新匹配, error: {e}"
            )
            self.timer.go_main_page()
            self._go_map_page()
            self._go_fight_prepare_page()


class EventFightInfo20240930(Event, NormalFightInfo):
    def __init__(self, timer: Timer, chapter_id, map_id, event="20240930") -> None:
        NormalFightInfo.__init__(self, timer, chapter_id, map_id)
        Event.__init__(self, timer, event)
        self.map_image = (
            self.common_image["easy"]
            + self.common_image["hard"]
            + self.event_image[1]
            + self.event_image[2]
        )
        self.end_page = "unknown_page"
        self.state2image["map_page"] = [self.map_image, 5]
