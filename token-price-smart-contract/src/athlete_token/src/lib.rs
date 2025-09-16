#![no_std]
use soroban_sdk::{contractimpl, symbol, Env};

pub struct AthleteToken;

#[contractimpl]
impl AthleteToken {
    pub fn hello(env: Env) -> symbol::Symbol {
        symbol!("Hello, Soroban!")
    }
}














