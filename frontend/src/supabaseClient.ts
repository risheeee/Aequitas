import { createClient } from '@supabase/supabase-js'

// Replace with your actual credentials from Supabase Settings
const supabaseUrl = 'https://ajkspdmsohmfpzqoqwzc.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFqa3NwZG1zb2htZnB6cW9xd3pjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjUyOTA5NzAsImV4cCI6MjA4MDg2Njk3MH0.o_idKHTeprBsfxaIph3Pdg__5q9lU9aCeI3giTEr7ug'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)