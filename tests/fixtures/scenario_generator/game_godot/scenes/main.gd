# Godot main scene script — fixture for game_godot discoverer.
extends Node2D

var score: int = 0


# Called once when the node enters the scene tree.
func _ready() -> void:
	print("Scene ready")


# Called every frame. `delta` is seconds since previous frame.
func _process(delta: float) -> void:
	score += int(delta * 100)


# Called every physics step at a fixed interval.
func _physics_process(delta: float) -> void:
	pass


# Called for every input event before _unhandled_input.
func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		print("Accept pressed")


# Called when an input event is not handled by anything else.
func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel"):
		get_tree().quit()
