<?php

/**
 * Tiny Laravel routes fixture for the web_service_php discoverer.
 */

use Illuminate\Support\Facades\Route;

/** List all users in the system. */
Route::get('/users', function () {
    return [];
});

/** Create a new order and return its id. */
Route::post('/orders', function () {
    return ['id' => 1];
});

/** Delete the order with the given id. */
Route::delete('/orders/{id}', function ($id) {
    return null;
});
