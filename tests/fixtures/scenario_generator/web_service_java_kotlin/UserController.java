package com.example.fixture;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
public class UserController {

    /**
     * List all users in the system.
     */
    @GetMapping("/list")
    public Object listUsers() {
        return new Object();
    }

    /**
     * Create a new user and return its id.
     */
    @PostMapping("/create")
    public Object createUser() {
        return new Object();
    }

    /**
     * Delete a user by id.
     */
    @DeleteMapping("/delete")
    public Object deleteUser() {
        return null;
    }
}
