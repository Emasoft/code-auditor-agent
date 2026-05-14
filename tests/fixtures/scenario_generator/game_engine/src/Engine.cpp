// Engine.cpp — Custom C++ game engine implementation. Contains the
// SceneGraph and ShaderCompiler marker so the game_engine fingerprint
// fires.
#include "Engine.h"

#include <cstdio>

// Stub SceneGraph — real engines maintain a tree of scene nodes here.
class SceneGraph
{
public:
	void tick(float /*dt*/) {}
};

// Stub ShaderCompiler — real engines lower HLSL/GLSL to SPIR-V here.
class ShaderCompiler
{
public:
	void compile(const char* /*src*/) {}
};

Engine::Engine() : m_scene(new SceneGraph()), m_renderer(nullptr) {}

Engine::~Engine()
{
	delete m_scene;
}

void Engine::update(float dt)
{
	m_scene->tick(dt);
}

void Engine::render()
{
	if (m_renderer)
		m_renderer->render();
}

void Engine::onKeyDown(int keycode)
{
	std::printf("keydown: %d\n", keycode);
}

void Engine::onMouseDown(int button, int x, int y)
{
	std::printf("mousedown: %d (%d,%d)\n", button, x, y);
}
