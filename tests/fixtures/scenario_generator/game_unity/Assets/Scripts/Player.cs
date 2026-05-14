// Unity Player MonoBehaviour — fixture for game_unity discoverer.
// Covers the four canonical lifecycle/event callbacks.
using UnityEngine;

public class Player : MonoBehaviour
{
    // Called once at scene load — initialization hook.
    void Start()
    {
        Debug.Log("Player initialized");
    }

    // Called every rendered frame — game tick.
    void Update()
    {
        // Per-frame logic.
    }

    // Called at a fixed physics interval — physics tick.
    void FixedUpdate()
    {
        // Physics-step logic.
    }

    // Called when a collider enters another collider — input/world event.
    void OnCollisionEnter(Collision collision)
    {
        Debug.Log("Collision: " + collision.gameObject.name);
    }
}
