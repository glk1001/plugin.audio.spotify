import os
from xml.etree import ElementTree

import xbmcvfs
from xbmc import LOGDEBUG

from utils import ADDON_ID, log_msg


class HttpVideoPlayerSetter:
    def __init__(self):
        self.__plugin_name = ADDON_ID
        self.__player_rules_filename = xbmcvfs.translatePath(
            f"special://masterprofile/playercorefactory.xml"
        )

    def set_http_rule(self) -> bool:
        if not os.path.exists(self.__player_rules_filename):
            self.__create_new_player_rules()
            log_msg(f"Created a new file '{self.__player_rules_filename}' with a video http rule.")
            return True
        else:
            if self.__add_http_rule():
                log_msg(f"Added a video http rule to '{self.__player_rules_filename}'")
                return True

            log_msg(
                f"There is already a video http rule in '{self.__player_rules_filename}'."
                " Nothing to do.",
                LOGDEBUG,
            )
            return False

    def __create_new_player_rules(self) -> None:
        xml_str = f"""<?xml version='1.0' encoding='utf-8'?>
<playercorefactory>
  <!-- This file created by the '{self.__plugin_name}' addon. -->     
  <rules name="system rules">
    <rule name="http" protocols="http" player="VideoPlayer" />
  </rules>
</playercorefactory>
"""
        with open(self.__player_rules_filename, "w") as f:
            f.write(xml_str)

    def __add_http_rule(self) -> bool:
        class CommentedTreeBuilder(ElementTree.TreeBuilder):
            def comment(self, data):
                self.start(ElementTree.Comment().tag, {})
                self.data(data)
                self.end(ElementTree.Comment().tag)

        parser = ElementTree.XMLParser(target=CommentedTreeBuilder())
        tree = ElementTree.parse(self.__player_rules_filename, parser=parser)
        root = tree.getroot()

        http_rule = root.findall("./rules/rule/[@protocols='http']")
        if http_rule:
            return False

        rules = root.find("./rules")

        attributes = {
            "name": "http",
            "protocols": "http",
            "player": "VideoPlayer",
        }
        new_rule = ElementTree.Element("rule", attributes)
        new_rule.tail = "\n\n" + "    "
        rules.insert(0, new_rule)

        comment = ElementTree.Comment(
            f" This http rule added by the '{self.__plugin_name}' addon. "
        )
        comment.tail = "\n" + "    "
        rules.insert(0, comment)

        xml_str = ElementTree.tostring(root, encoding="unicode", xml_declaration=True)

        with open(self.__player_rules_filename, "w") as f:
            f.write(xml_str)
            f.write("\n")

        return True
