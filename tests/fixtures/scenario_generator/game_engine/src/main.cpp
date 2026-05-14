// main.cpp — game engine entry point.
#include "Engine.h"

#include <chrono>
#include <thread>

int main(int argc, char* argv[])
{
	(void)argc;
	(void)argv;

	Engine engine;
	using clock = std::chrono::steady_clock;
	auto last = clock::now();
	for (int frame = 0; frame < 60; ++frame)
	{
		auto now = clock::now();
		float dt = std::chrono::duration<float>(now - last).count();
		last = now;
		engine.update(dt);
		engine.render();
		std::this_thread::sleep_for(std::chrono::milliseconds(16));
	}
	return 0;
}
