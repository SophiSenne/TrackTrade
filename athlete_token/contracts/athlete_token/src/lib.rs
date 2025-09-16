#![no_std]

use soroban_sdk::{contract, contractimpl, contracttype, Env, Address};

// Estrutura de dados do contrato (opcional, não está sendo usada atualmente)
#[contracttype]
pub struct AthleteTokenArgs {
    pub owner: Address,
    pub amount: i128,
}

// Contract client definition
#[contract]
pub struct AthleteToken;

#[contractimpl]
impl AthleteToken {
    // Retorna saldo
    pub fn balance(env: Env, owner: Address) -> i128 {
        env.storage()
            .persistent()
            .get::<Address, i128>(&owner)
            .unwrap_or(0) // Changed from Ok(0) to just 0
    }

    // Mint de tokens
    pub fn mint(env: Env, owner: Address, amount: i128) {
        let storage = env.storage().persistent();
        let current: i128 = storage.get::<Address, i128>(&owner).unwrap_or(0); // Fixed
        storage.set(&owner, &(current + amount));
    }

    // Transferência de tokens
    pub fn transfer(env: Env, from: Address, to: Address, amount: i128) -> bool {
        let storage = env.storage().persistent();
        let from_balance: i128 = storage.get::<Address, i128>(&from).unwrap_or(0); // Fixed
        if from_balance < amount {
            return false;
        }
        let to_balance: i128 = storage.get::<Address, i128>(&to).unwrap_or(0); // Fixed
        storage.set(&from, &(from_balance - amount));
        storage.set(&to, &(to_balance + amount));
        true
    }
}