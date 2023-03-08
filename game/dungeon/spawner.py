import random

from ..entities import Creature
from ..config import enemies
from ..components.component import WanderingAI

class Spawner:

    # TODO
    @staticmethod
    def spawn_player():
        pass

    # TODO refactor dungeon and pass max_entities_per_room to method.
    @staticmethod
    def spawn_random_enemy_instance() -> object:
        enemy_data: dict = random.choices(
            population=list(enemies.values()),
            weights=[enemy["spawn_chance"] for enemy in enemies.values()]
        )[0]
        print(enemy_data)
        enemy = Creature(
            x=-1,
            y=-1,
            name=enemy_data["name"],
            char=enemy_data["char"],
            color=enemy_data["color"],
            hp=enemy_data["hp"],
            dmg=enemy_data["dmg"]
        )
        enemy.add_component("ai", WanderingAI(enemy))
        return enemy
    

    # TODO??
    @staticmethod
    def spawn_random_enemy_instances() -> list[object]:
        pass