from __future__ import annotations
from pathlib import Path

import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path
    from .engine import Engine
    from .save_handling import Save
    from .components.fighter import Fighter
    from .components.leveler import Leveler
    from .dungeon.floor import Floor
    from .components.equippable import Equippable
    from .components.inventory import Inventory
from .dungeon.dungeon import Dungeon
from .entities import Creature, Entity, Item, Weapon, Player
from .rng import RandomNumberGenerator
from .modes import GameStatus, GameMode
from .message_log import MessageType
from .tile import *
from .save_handling import (
    Save,
    save_current_game,
    save_to_dir,
    delete_save_slot,
    fetch_saves
)


class Action:
    """Base action"""

    def __init__(self, entity: Entity):
        self.entity = entity

    def perform(self) -> None:
        """Overridable method"""
        pass


class ItemAction(Action):
    """Base item action for an entity performing something with it"""

    def __init__(self, entity: Entity, item: Item):
        super().__init__(entity)
        self.item = item


    def perform(self, engine: Engine) -> bool:
        # Prevent circular import.
        from .gamestates import InventoryMenuState, ExploreState
        turnable: bool = False

        if self.item.get_component("consumable") is not None:
            self.item.consumable.perform(engine)

        elif (
            self.item.get_component("projectable") is not None
            and not isinstance(engine.gamestate, InventoryMenuState)
        ):
            turnable = self.item.projectable.perform(engine)
            engine.gamestate = ExploreState(self.entity)  # Go back after use.
            return turnable

        elif self.item.get_component("equippable") is not None:
            self.item.equippable.perform(engine)
        
        return turnable


class HandleSpecialWeaponAction(Action):
    """Determine whether a weapon is able to perform a special action.
    
    A weapon is 'special' if, at a target, shoots a projectile, heals, damages,
    or applies some other effect during the explore state
    """

    def __init__(self, entity: Entity, weapon: Optional[Weapon]):
        super().__init__(entity)
        self._weapon = weapon

    def perform(self, engine: Engine) -> bool:
        # Prevent circular import.
        from .gamestates import ExploreState, ProjectileTargetState
        turnable: bool = True

        # No valid special weapon.
        if self._weapon is None:
            turnable = False
            if not isinstance(engine.gamestate, ExploreState):
                engine.gamestate = ExploreState(self.parent)
            return turnable
        
        if self._weapon.get_component("projectable") is not None:
            if self._weapon.projectable.uses_left <= 0:
                turnable = False
                # TODO add out of charge message property to component.
                engine.message_log.add("The staff fizzles with no charge left")
                return turnable
            if not isinstance(engine.gamestate, ProjectileTargetState):
                engine.gamestate = ProjectileTargetState(
                    self.entity, self._weapon)
        
        return turnable


class PickUpItemAction(Action):
    """Pick an item from off the floor and add it to inventory.
    
    It is not an `ItemAction` because we don't know if there's an item on the
    ground to be picked up at first - can't pass it to the constructor.
    """
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False
        
        inventory: Inventory = self.entity.inventory
        floor: Floor = engine.dungeon.current_floor
        item_to_pick_up: Optional[Item] = None
        
        # Check if an item actually exists at the carrier's location.
        for item in floor.items:
            if item.x == self.entity.x and item.y == self.entity.y:
                item_to_pick_up = item
                break
        
        # No item found underneath entity.
        if item_to_pick_up is None:
            engine.message_log.add("Nothing to be picked up here", color="red")
            return turnable

        # Not enough space in carrier's inventory.
        if inventory.size >= inventory.max_slots:
            if self.entity == engine.player:
                engine.message_log.add(
                    "There is not enough space in your inventory", color="red")
            return turnable
        
        # Pick up the item.
        floor.entities.remove(item)
        inventory.add_item(item)
        item.parent = self.entity

        engine.message_log.add(
            f"You picked up: {item.name.lower()}", color="blue")

        return turnable
        

class DropItemAction(ItemAction):
    """Remove from inventory and drop an item onto the floor"""
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        inventory: Inventory = self.entity.inventory
        floor: Floor = engine.dungeon.current_floor
        
        # Unequip item if it is equipped.
        equippable: Equippable = self.item.get_component("equippable")
        if equippable and inventory.is_equipped(self.item):
            equippable.perform(engine)

        inventory.remove_item(self.item)
        self.item.place(floor, self.entity.x, self.entity.y)

        engine.message_log.add(
            f"You dropped: {self.item.name.lower()}", color="blue")
        
        return turnable


class OnPlayerDeathAction(Action):
    """Save game with updated defeat status, rendering it unplayable"""

    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        engine.message_log.add("You have been defeated!", color="red")
        
        engine.save_meta["status"] = GameStatus.DEFEAT
        save_current_game(engine)
        
        return turnable


class OnPlayerWinAction(Action):
    """Save game with updated victory status.
    
    Player cannot return to game after making it out the dungeon.
    """

    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        engine.message_log.add("You made it out of the dungeon!", color="gold")

        engine.save_meta["status"] = GameStatus.VICTORY
        save_current_game(engine)

        return turnable


class FromSavedataAction(Action):
    """Base action given save information"""
    
    def __init__(self, save: Save, saves_dir: Path, index: int) -> bool:
        self.save = save
        self.saves_dir = saves_dir
        self.index = index
    
    
    def _load_data_to_engine(self, engine: Engine, save: Save) -> None:
        """Loads a given save data into the engine"""
        engine.save = save
        engine.save_meta = save.metadata
        engine.player = save.data.get("player")
        engine.dungeon = save.data.get("dungeon")
        engine.message_log = save.data.get("message_log")
        engine.rng = save.data.get("rng")


class DeleteSaveAction(FromSavedataAction):
    """Delete the selected save slot by index"""
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False
        
        # Delete save and refresh saves list.
        save: Save = fetch_saves(self.saves_dir)[self.index]
        delete_save_slot(save)
        engine.gamestate.saves = fetch_saves(self.saves_dir)
        
        return turnable


class SaveAction(Action):
    """Saves the game"""
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False
        
        save_current_game(engine)
        
        return turnable


class QuitGameAction(Action):
    """Exit program"""

    def perform(self, engine: Engine):
        sys.exit(0)


class SaveAndQuitAction(SaveAction):
    """Saves the game and exits program"""

    def perform(self, engine: Engine) -> bool:
        super().perform(engine)
        QuitGameAction(self.entity).perform(engine)


class StartNewGameAction(FromSavedataAction):
    """Start the dungeon crawling on the selected gamemode"""

    def __init__(self,
                 save: Save,
                 saves_dir: Path,
                 index: int,
                 player_name: str,
                 seed: str) -> bool:
        super().__init__(save, saves_dir, index)
        self._player_name = player_name.strip()
        self._seed = seed.strip()

    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        # Set player name.
        self.save.data["player"].name = self._player_name
        self.save.data["player"].og_name = self._player_name
        if self.save.data["player"].name == "":
            self.save.data["player"].name = "Player"
            self.save.data["player"].og_name = "Player"
        
        # Set seed.
        self.save.data["rng"] = RandomNumberGenerator(
            None if self._seed == "" else self._seed
        )
        
        save_to_dir(self.saves_dir, self.index, self.save)
        self._load_data_to_engine(engine, self.save)

        engine.dungeon.start()
        engine.dungeon.spawn_player(engine.player)
        
        save_current_game(engine)
        
        return turnable


class ContinueGameAction(FromSavedataAction):
    """Continue a previous save"""

    def perform(self, engine: Engine) -> bool:
        turnable: bool = False
        
        self._load_data_to_engine(engine, self.save)

        engine.message_log.add(
            f"Welcome back, {engine.player.name}!", color="blue")
        
        return turnable


class LevelUpAction(Action):
    """Handle logic for leveling up an entity"""

    def __init__(self, entity: Entity, attribute: Fighter.AttributeType):
        super().__init__(entity)
        self.attribute = attribute
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False
        
        leveler: Leveler = self.entity.leveler
        leveler.level_up()
        leveler.increment_attribute(self.attribute)

        engine.message_log.add(
            message=f"Leveled up to {leveler.level}",
            type=MessageType.INFO, color="green")

        return turnable


class DoNothingAction(Action):
    """Do nothing this turn"""

    def perform(self, engine: Engine) -> bool:
        # Prevent circular import.
        from .gamestates import ExploreState , ProjectileTargetState
        turnable: bool = True

        if isinstance(engine.gamestate, ProjectileTargetState):
            turnable = False
            return turnable

        if isinstance(engine.gamestate, ExploreState):
            engine.message_log.add("You take no action")
            engine.save_meta["turns"] += 1  # Record turn.

        return turnable


class DescendStairsAction(Action):
    """Descend a flight of stairs to the next dungeon level.
    
    Normal mode dungeon does not have this staircase on the last floor.
    """
    
    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        dungeon: Dungeon = engine.dungeon
        floor: Floor = dungeon.current_floor

        player_x = engine.player.x
        player_y = engine.player.y
        
        # Ensure there exists a staircase to begin with.
        if floor.descending_staircase_location is None:
            engine.message_log.add("Can't descend here", color="red")
            return turnable
        
        # Check if player is standing on the staircase tile.
        staircase_x, staircase_y = floor.descending_staircase_location 
        if not (player_x == staircase_x and player_y == staircase_y):
            engine.message_log.add("Can't descend here", color="red")
            return turnable
        
        # Go down a level and generate new floor if needed.
        new_depth_reached: bool = \
            dungeon.current_floor_index == dungeon.deepest_floor_index
        dungeon.current_floor_index += 1  # Keep this here!!!
        if new_depth_reached:
            dungeon.generate_next_floor()

        dungeon.spawner.spawn_player(
            engine.player,
            dungeon.current_floor.first_room
        )
        
        engine.message_log.add(
            "You descend a level...", color="blue")
        
        engine.save_meta["turns"] += 1  # Record turn.
        
        return turnable


class AscendStairsAction(Action):
    """Ascend a flight of stairs to the previous dungeon level.
    
    Endless mode dungeon does not have this staircase on the first floor.
    """
    
    def perform(self, engine: Engine) -> bool:
        # Prevent circular import.
        from .gamestates import GameWinEndState

        turnable: bool = False

        dungeon: Dungeon = engine.dungeon
        floor: Floor = dungeon.current_floor

        player_x = engine.player.x
        player_y = engine.player.y
        
        # Ensure there exists a staircase to begin with.
        if floor.ascending_staircase_location is None:
            engine.message_log.add("Can't ascend here", color="red")
            return turnable
        
        # Check if player is standing on the staircase tile.
        staircase_x, staircase_y = floor.ascending_staircase_location 
        if not (player_x == staircase_x and player_y == staircase_y):
            engine.message_log.add("Can't ascend here", color="red")
            return turnable

        # Check quest completion status.
        if dungeon.on_first_floor:
            # Quest complete - end game.
            if engine.player.inventory.has_quest_item:
                engine.gamestate = GameWinEndState(self.entity)
                return turnable
            # Quest not complete - block player.
            else:
                engine.message_log.add("You must bring back the relic first!")
                return turnable
        
        # Go up a level.
        dungeon.current_floor_index -= 1
        dungeon.spawner.spawn_player(
            engine.player,
            dungeon.current_floor.last_room
        )
        
        engine.message_log.add(
            "You ascend a level...", color="blue")
        
        engine.save_meta["turns"] += 1  # Record turn.
        
        return turnable


class ActionWithDirection(Action):
    """Base action with (x, y) directioning"""

    def __init__(self, entity: Creature, dx: int, dy: int):
        super().__init__(entity)
        self.dx = dx
        self.dy = dy


class BumpAction(ActionWithDirection):
    """Action to decide what happens when a creature moves to a desired tile"""

    def __init__(
        self,
        entity: Creature,
        dx: int,
        dy: int,
        no_hit: bool = False
    ):
        super().__init__(entity, dx, dy)
        # If on, the bump action will not attempt to hit the blocking entity.
        self._no_hit = no_hit

    def perform(self, engine: Engine) -> bool:
        # Prevent circular import.
        from .components.ai import AllyAI

        turnable: bool = False
        floor = engine.dungeon.current_floor

        desired_x = self.entity.x + self.dx
        desired_y = self.entity.y + self.dy

        blocking_entity: Optional[Entity] = floor.blocking_entity_at(
            desired_x, desired_y)

        # TODO refactor.
        if blocking_entity is not None and not self._no_hit:
            # Switch places with ally, for example, instead of hitting them.
            bumper_is_player: bool = self.entity == engine.player
            if (
                bumper_is_player
                and isinstance(blocking_entity.get_component("ai"), AllyAI)
            ):
                temp_x: int = self.entity.x
                temp_y: int = self.entity.y
                self.entity.x = blocking_entity.x
                self.entity.y = blocking_entity.y
                blocking_entity.x = temp_x
                blocking_entity.y = temp_y
                turnable = True
                return turnable

            return MeleeAction(self.entity, self.dx, self.dy).perform(engine)
        else:
            return WalkAction(self.entity, self.dx, self.dy).perform(engine)


class WalkAction(ActionWithDirection):
    """Action to validly move a creature"""

    def perform(self, engine: Engine) -> bool:
        turnable: bool = False

        floor = engine.dungeon.current_floor

        desired_x = self.entity.x + self.dx
        desired_y = self.entity.y + self.dy

        # Get within bounds.
        if (
            (desired_x > floor.height - 1 or desired_x < 0)
            or (desired_y > floor.width - 1 or desired_y < 0)
        ):
            engine.message_log.add("Out of bounds", color="red")
            return turnable

        # Get blocking tiles.
        if not floor.tiles[desired_x][desired_y].walkable:
            if self.entity == engine.player:
                engine.message_log.add("That way is blocked", color="red")
            return turnable

        # Get blocking entities.
        if floor.blocking_entity_at(desired_x, desired_y):
            return turnable
    
        turnable = True

        self.entity.move(dx=self.dx, dy=self.dy)

        if isinstance(self.entity, Player):
            engine.save_meta["turns"] += 1  # Record turn.
        
        return turnable


class MeleeAction(ActionWithDirection):
    """Action to hit a creature within melee range"""

    def perform(self, engine: Engine) -> bool:
        turnable: bool = True

        floor = engine.dungeon.current_floor

        desired_x = self.entity.x + self.dx
        desired_y = self.entity.y + self.dy

        # Prepare both parties and their respective combat components.
        initiator: Creature = self.entity
        initiator_fighter: Fighter = initiator.fighter
        initiator_leveler: Leveler = initiator.leveler

        target: Creature = floor.blocking_entity_at(desired_x, desired_y)
        target_fighter: Fighter = target.fighter
        target_leveler: Leveler = target.leveler
        
        target_slain_message: str = f"{target.og_name} has perished!"
        battle_message: str = ""
        message_type: MessageType = MessageType.INFO
        message_color: str = ""

        if initiator == engine.player:  # Record player.
            engine.save_meta["turns"] += 1

        # Chance to hit opponent fails.
        did_hit: bool = initiator_fighter.check_hit_success()
        if not did_hit:
            if target == engine.player:
                battle_message += f"{initiator.og_name} missed you"
                message_color = "blue"
                message_type = MessageType.ENEMY_ATTACK
            elif initiator == engine.player:
                battle_message += f"You missed {target.og_name}"
                message_color = "red"
                message_type = MessageType.PLAYER_ATTACK
            else:
                return turnable

            engine.message_log.add(
                message=battle_message, type=message_type, color=message_color)

            return turnable
        
        # Modify damage given/received based on opponents' stats.

        # Do it again if succeeds double hit check.
        did_double_hit: bool = initiator_fighter.check_double_hit_success()
        if did_double_hit and initiator == engine.player:
            engine.message_log.add(
                "Double hit!", color=(
                    "green" if initiator == engine.player else "red"))
        for i in range(2 if did_double_hit else 1):
            # Critical hit check.
            did_critical: bool = initiator_fighter.check_critical_hit_success()
            damage_given: int = 0
            if did_critical:
                damage_given = initiator_fighter.critical_damage
            else:
                damage_given = initiator_fighter.damage
            target_fighter.take_damage(damage_given)
            
            # Log hit success.
            if target == engine.player:
                battle_message = f"{initiator.og_name} hits you for " \
                                 f"{damage_given} pts"
                message_type = MessageType.ENEMY_ATTACK
                message_color = "red"
            elif initiator == engine.player:
                battle_message = f"You hit {target.og_name} for " \
                                 f"{damage_given} pts"
                message_type = MessageType.PLAYER_ATTACK
                message_color="blue"
            else:
                return turnable

            battle_message += " !!!" if did_critical else ""
            
            engine.message_log.add(
                message=battle_message, type=message_type, color=message_color)
        
        # TODO add check for player or enemy knockout.

        # Target opponent has been slain.
        if target_fighter.is_dead:
            experience_drop: int = target.leveler.experience_drop
            floor.entities.remove(target)
            floor.add_entity(target)
            engine.message_log.add(target_slain_message)

            if initiator == engine.player:
                engine.save_meta["slayed"] += 1
                engine.message_log.add(
                    message=f"You slayed {target.og_name} " \
                            f"and gained {experience_drop} EXP!",
                    type=MessageType.INFO, color="green")

            # Absorb experience.
            initiator_leveler.absorb(
                incoming_experience=target_leveler.experience_drop)
        
        return turnable

