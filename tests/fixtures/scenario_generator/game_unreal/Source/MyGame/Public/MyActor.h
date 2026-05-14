// MyActor.h — Unreal Engine actor header — fixture for game_unreal discoverer.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "MyActor.generated.h"

UCLASS()
class MYGAME_API AMyActor : public AActor
{
	GENERATED_BODY()

public:
	// Sets default values for this actor's properties.
	AMyActor();

protected:
	// Called when the game starts or when spawned.
	virtual void BeginPlay() override;

public:
	// Called every frame.
	virtual void Tick(float DeltaTime) override;

	// Server-side RPC callable from the client.
	UFUNCTION(Server, Reliable)
	void ServerFireWeapon();

	// Client-broadcast event from the server.
	UFUNCTION(NetMulticast, Reliable)
	void MulticastPlayEffect();

	// Blueprint-callable input handler bound to the "Jump" action.
	UFUNCTION(BlueprintCallable, Category = "Input")
	void OnJumpPressed();
};
