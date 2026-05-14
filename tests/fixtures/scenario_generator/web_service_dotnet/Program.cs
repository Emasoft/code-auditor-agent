// Tiny ASP.NET Core minimal-API fixture for the web_service_dotnet discoverer.

var builder = WebApplication.CreateBuilder(args);
var app = builder.Build();

/// <summary>List all users in the system.</summary>
app.MapGet("/users", () => Array.Empty<object>());

/// <summary>Create a new order and return its id.</summary>
app.MapPost("/orders", (object payload) => new { id = 1 });

/// <summary>Delete the order with the given id.</summary>
app.MapDelete("/orders/{id}", (int id) => Results.NoContent());

app.Run();
