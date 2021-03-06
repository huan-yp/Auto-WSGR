BB = "BB"
BC = "BC"
CL = "CL"
CV = "CV"
CA = "CA"
CVL = "CVL"
NAP = "NAP"
DD = "DD"
SS = "SS"
CLT = "CLT"
BM = "BM"
AV = "AV"
AADG = "AADG"
ASDG = "ASDG"
BG = "BG"
CBG = "CBG"
NO = "NO"
BBV = "BBV"
CAV = "CAV"
SC = "SC"
SAP = "SAP"

"""舰船类型,参考游戏中显示的字符串,特殊和陌生的命名在下面给出,路基等单位暂时无数据
    NAP:常规补给舰,胖次期特殊点位刷六个那种,或者说除了掉胖次的之外的所有(包括我方)
    SAP:特殊补给舰,胖次期掉胖次的蓝色补给舰
    CBG:导弹巡洋舰
    CAV:航巡
    SC:炮潜
    BG:导战
    NO:该位置不存在舰船
"""

ALL_UI = {'map_page', 'main_page', 'decisive_battle_entrance', 'exercise_page', 'battle_page', 'expedition_page',
          'fight_prepare_page', 'bath_page', 'choose_repair_page', 'backyard_page', 'canteen_page',
          'options_page', 'build_page', 'destroy_page', 'develop_page', 'discard_page',
          'intensify_page', 'remake_page', 'skill_page', 'mission_page', 'support_set_page',
          'friend_page', }
"""名字说明:
'fight_prepare_page':包含了快速修理,补给,综合属性等选项的界面
"""


FIGHT_RESULTS = {"SS", "S", "A", "B", "C", "D"}

NODE_LIST = [None, range(1, 6), range(1, 7), range(1, 5), range(1, 5),
             range(1, 6), range(1, 5), range(1, 6), range(1, 6)]

RESOURCE_NAME = {'oil', 'ammo', 'steel', 'aluminum', 'diamond', 'quick_repair', 'quick_build', \
    'ship_blueprint', 'equipment_builprint', }

#船舱容量,装备容量
PORT_FACILITIES = {'ship_limit', 'ship_ammount', 'equipment_limit', 'equipment_ammount'}

#维修船坞,建造位,开发位



INFO1 = 13
INFO2 = 16
INFO3 = 19
