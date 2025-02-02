from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .dungeon.room import Room
    from .dungeon.floor import Floor
from .components.inventory import Inventory
from .components.fighter import Fighter
from .components.leveler import Leveler
from .render_order import RenderOrder
from .entities import (
    Entity, Item, Potion, Weapon, Staff, Armor, Creature, Player)
from .item_types import WeaponType, ProjectileType, ArmorType, PotionType
from .rng import RandomNumberGenerator

from .data.creatures import enemies, player
from .data.items.potions import restoration_potions
from .data.items.weapons import weapons
from .data.items.staves import staves
from .data.items.armor import armor
from .data.config import DESCENDING_STAIRCASE_TILE, ASCENDING_STAIRCASE_TILE

class Spawner:
    """Helper object for spawning entities in the dungeon"""
    
    def __init__(self, rng: RandomNumberGenerator):
        self.rng = rng
        # Create staircase prefabs.
        self.descending_staircase: Entity = Entity(
            x=-1, y=-1,
            name="Descending staircase",
            char=DESCENDING_STAIRCASE_TILE,
            color="white",
            render_order=RenderOrder.STAIRCASE,
            blocking=False
        )
        self.ascending_staircase: Entity = copy.deepcopy(
            self.descending_staircase)
        self.ascending_staircase.name = "Ascending staircase"
        self.ascending_staircase.char = ASCENDING_STAIRCASE_TILE


    def spawn_staircase(
        self, floor: Floor, x: int, y: int, type: str) -> Entity:
        """Place a descending or ascending staircase somewhere in the level"""
        staircase: Entity = None
        
        if type == "descending":
            staircase = self.descending_staircase.spawn_clone()
            floor.descending_staircase_location = x, y
        elif type == "ascending":
            staircase = self.ascending_staircase.spawn_clone()
            floor.ascending_staircase_location = x, y
        
        staircase.x = x
        staircase.y = y
        
        floor.add_entity(staircase)
        
        return staircase
        
    
    def spawn_player(self, player: Player, room: Room) -> None:
        """Place the player in a selected room"""
        x, y = room.get_center_cell()  # On top of a staircase.
        player.x, player.y =  x, y
        room.floor.add_entity(player)
    
    
    def spawn_enemy(self, room: Room) -> None:
        """Spawn a random creature and place it inside a room"""
        x, y = room.get_random_empty_cell()

        enemy: Creature = self._get_random_enemy_instance()
        enemy.x, enemy.y = x, y
        
        room.floor.add_entity(enemy)
    
    
    def spawn_item(self, room: Room, is_quest_item: bool = False) -> None:
        """Spawn a random item and place it inside a room"""
        x, y = room.get_random_empty_cell()
        
        item: Optional[Item] = None
        if is_quest_item:
            item = self._get_quest_item_instance()
        else:
            item = self._get_random_item_instance()
        item.x, item.y = x, y
        
        room.floor.add_entity(item)


    def get_player_instance(self) -> Player:
        """Load player data and create an instance out of it"""
        player_obj = Player(
            x=-1, y=-1,
            name=player["name"],
            char=player["char"],
            color=player["color"],
            render_order=RenderOrder.CREATURE,
        )

        player_obj.add_component(
            name="fighter",
            component=Fighter(  # Refer to fighter.py for base stats.
                rng=self.rng,
                base_health=100,
                base_magicka=100,
                base_damage=8,
                base_agility=1,
                base_power=1,
                base_sage=1,
                base_vitality=1
            )
        )
        player_obj.add_component("leveler", Leveler(rng=self.rng, start_level=1))
        player_obj.leveler.set_starting_attributes()
        player_obj.add_component("inventory", Inventory(num_slots=16))
        
        return player_obj


    def _get_random_enemy_instance(self) -> Creature:
        """Load enemy data and create an instance out of it"""
        # Prevent circular import.
        from .components.ai import WanderingAroundRoomAI

        # Fetch a random enemy data object.
        enemy_data: dict = self.rng.choices(
            population=list(enemies.values()),
            weights=[enemy["spawn_chance"] for enemy in enemies.values()]
        )[0]
        
        # Create the instance and spawn the enemy.
        enemy = Creature(
            x=-1, y=-1,
            name=enemy_data["name"],
            char=enemy_data["char"],
            color=enemy_data["color"],
            render_order=RenderOrder.CREATURE,
            energy=enemy_data["energy"]
        )

        enemy.add_component(
            name="fighter",
            component=Fighter(
                rng=self.rng,
                base_health=enemy_data["hp"],
                base_magicka=1,
                base_damage=enemy_data["dmg"],
                base_agility=1,
                base_power=1,
                base_sage=1,
                base_vitality=1
            )
        )
        enemy.add_component(
            "leveler", Leveler(rng=self.rng, start_level=1, base_drop_amount=5))
        enemy.leveler.set_starting_attributes()
        enemy.add_component("ai", WanderingAroundRoomAI(enemy))

        return enemy


    def _get_random_item_instance(self) -> Item:
        """Load item data and create an instance out of it"""
        factory_pool: dict = [
            {
                "factory": WeaponFactory(self.rng, item_pool=weapons),
                "spawn_chance": 20
            },
            {
                "factory": StaffFactory(self.rng, item_pool=staves),
                "spawn_chance": 100
            },
            {
                "factory": ArmorFactory(self.rng, item_pool=armor),
                "spawn_chance": 20
            },
            {
                "factory": PotionFactory(
                    self.rng, item_pool=restoration_potions),
                "spawn_chance": 20
            },
        ]

        item_factory: ItemFactory = self.rng.choices(
            population=factory_pool,
            weights=[
                factory["spawn_chance"]
                for factory in factory_pool
            ]
        )[0]["factory"]

        return item_factory.get_random_item()
    

    def _get_quest_item_instance(self) -> Item:
        """Get the item to be picked up """
        # Prevent circular import.
        from .components.quest_item import QuestItem

        item: Item = Item(
            x=-1, y=-1,
            name="Relic of Vai", char="&",
            color="gold",
            render_order=RenderOrder.ITEM,
            blocking=False
        )
        item.add_component("quest_item", QuestItem())

        return item


class ItemFactory:
    """Base factory for spitting out items to spawn throughout the dungeon"""

    def __init__(self,
                 rng: RandomNumberGenerator,
                 item_pool: list[dict[str, Any]]):
        self.rng = rng
        self._item_data: dict = self.rng.choices(
            population=item_pool,
            weights=[
                item["spawn_chance"]
                for item in item_pool
            ]
        )[0]
    
    def get_instance_from_class(self, item_class: Item) -> Item:
        return item_class(
            x=-1, y=-1,
            name=self._item_data["name"],
            char=self._item_data["char"],
            color=self._item_data["color"],
            render_order=RenderOrder.ITEM,
            blocking=False
        )


class WeaponFactory(ItemFactory):
    """Process for instantiating a weapon from data"""
    
    def get_random_item(self) -> Weapon:
        # Prevent circular import.
        from .components.equippable import Wieldable

        weapon = self.get_instance_from_class(Weapon)
        weapon.add_component(
            "equippable", Wieldable(damage_bonus=self._item_data["dmg"])
        )

        if self._item_data["type"] == WeaponType.SWORD:
            weapon.weapon_type = WeaponType.SWORD
        elif self._item_data["type"] == WeaponType.STAFF:
            weapon.weapon_type = WeaponType.STAFF
        
        return weapon


class StaffFactory(WeaponFactory):
    """Process for instantiating a staff weapon from data"""

    def get_random_item(self) -> Staff:
        # Prevent circular import.
        from .components.projectable import (
            EffectPerTurnProjectable, LightningProjectable,
            HealingProjectable, RizzProjectable, ConfusionProjectable,
            FreezeProjectable
        )

        staff: Staff = super().get_random_item()

        match self._item_data["staff_type"]:
            case ProjectileType.LIGHTNING:
                staff.projectile_type = ProjectileType.LIGHTNING
                staff.add_component(
                    "projectable", LightningProjectable(
                        uses=self._item_data["uses"],
                        magicka_cost=self._item_data["magicka_cost"],
                        magic_damage=self._item_data["magic_dmg"]
                    )
                )
            case ProjectileType.HEALING:
                staff.projectile_type = ProjectileType.HEALING
                staff.add_component(
                    "projectable", HealingProjectable(
                        uses=self._item_data["uses"],
                        magicka_cost=self._item_data["magicka_cost"],
                        heal=self._item_data["hp"]
                    )
                )
            case ProjectileType.RIZZ:
                staff.projectile_type = ProjectileType.RIZZ
                staff.add_component(
                    "projectable", RizzProjectable(
                        uses=self._item_data["uses"],
                        magicka_cost=self._item_data["magicka_cost"],
                        turns_remaining=self._item_data["turns_remaining"]
                    )
                )
            case ProjectileType.CONFUSION:
                staff.projectile_type = ProjectileType.CONFUSION
                staff.add_component(
                    "projectable", ConfusionProjectable(
                        uses=self._item_data["uses"],
                        magicka_cost=self._item_data["magicka_cost"],
                        turns_remaining=self._item_data["turns_remaining"]
                    )
                )
            case ProjectileType.FREEZING:
                staff.projectile_type = ProjectileType.FREEZING
                staff.add_component(
                    "projectable", FreezeProjectable(
                        uses=self._item_data["uses"],
                        magicka_cost=self._item_data["magicka_cost"],
                        turns_remaining=self._item_data["turns_remaining"]
                    )
                )

        return staff

class ArmorFactory(ItemFactory):
    """Process for instantiating an armor piece from data"""

    def get_random_item(self) -> Armor:
        # Prevent circular import.
        from .components.equippable import Wearable

        armor = self.get_instance_from_class(Armor)
        armor.add_component(
            "equippable",
            Wearable(
                damage_reduction=self._item_data["dmg_reduct"],
                coverage=self._item_data["coverage"])
        )

        if self._item_data["type"] == ArmorType.HEAD:
            armor.armor_type = ArmorType.HEAD
        elif self._item_data["type"] == ArmorType.TORSO:
            armor.armor_type = ArmorType.TORSO
        elif self._item_data["type"] == ArmorType.LEGS:
            armor.armor_type = ArmorType.LEGS
        
        return armor


class PotionFactory(ItemFactory):
    """Process for instantiating a potion item from data"""

    def get_random_item(self) -> Potion:
        # Prevent circular import.
        from .components.consumable import RestoreConsumable

        potion = self.get_instance_from_class(Potion)
        potion.add_component(
            "consumable",
            RestoreConsumable(yield_amount=self._item_data["yield"])
        )

        # Create restore health potion.
        if self._item_data["type"] == PotionType.HEALTH:
            potion.consumable.potion_type = PotionType.HEALTH
        # Create restore magicka potion.
        elif self._item_data["type"] == PotionType.MAGICKA:
            potion.consumable.potion_type = PotionType.MAGICKA
        
        return potion

