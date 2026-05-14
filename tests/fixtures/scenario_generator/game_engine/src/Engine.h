// Engine.h — Custom C++ game engine header — fixture for game_engine.
#pragma once

#include <cstdint>

// SceneGraph fwd-decl — the engine owns one of these and tickles it
// each frame via update().
class SceneGraph;

// Forward-declared renderer interface.
class Renderer
{
public:
	virtual ~Renderer() = default;
	virtual void render() = 0;
};

// Engine — the top-level game loop driver.
class Engine
{
public:
	Engine();
	~Engine();

	// Cooperative frame tick: dt is seconds since the previous frame.
	void update(float dt);

	// Submit the current scene graph to the renderer.
	void render();

	// Forward an input event from the platform layer.
	void onKeyDown(int keycode);

	// Forward a mouse-button event from the platform layer.
	void onMouseDown(int button, int x, int y);

private:
	SceneGraph* m_scene;
	Renderer* m_renderer;
};
